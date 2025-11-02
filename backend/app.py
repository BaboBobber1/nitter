"""Flask-Anwendung für den Nitter Web-Scraper."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from storage import Storage
from nitter_client import NitterClient

APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"
CONFIG_EXAMPLE_PATH = APP_ROOT / "config.example.json"


def _ensure_config_file() -> Dict:
    """Stellt sicher, dass config.json existiert und lädt sie."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _setup_logging(log_path: str) -> logging.Logger:
    """Initialisiert Logging auf Datei und Konsole."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("nitter_scraper")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
    return logger


class EventBroker:
    """Verwaltet Server-Sent-Event-Queues."""

    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()

    def register(self) -> queue.Queue:
        client_queue: queue.Queue = queue.Queue()
        with self._lock:
            self._clients.append(client_queue)
        return client_queue

    def unregister(self, client_queue: queue.Queue) -> None:
        with self._lock:
            if client_queue in self._clients:
                self._clients.remove(client_queue)

    def publish(self, event_type: str, data: Dict) -> None:
        payload = json.dumps({"type": event_type, "data": data})
        with self._lock:
            for client in list(self._clients):
                try:
                    client.put_nowait(payload)
                except queue.Full:
                    # Queue voll – entferne Client.
                    self._clients.remove(client)


class Scheduler(threading.Thread):
    """Einfacher Polling-Scheduler."""

    daemon = True

    def __init__(
        self,
        storage: Storage,
        fetch_callback,
        poll_interval: int = 5,
        broker: Optional[EventBroker] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.fetch_callback = fetch_callback
        self.poll_interval = poll_interval
        self.broker = broker
        self.logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self.last_run: Optional[str] = None
        self.queue_size = 0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # noqa: D401 - Thread-Loop
        while not self._stop_event.is_set():
            try:
                targets = self.storage.get_targets()
                now = datetime.now(timezone.utc)
                for target in targets:
                    last_fetch = target["last_fetched_at"]
                    interval = int(target["poll_interval_seconds"] or 300)
                    due = True
                    if last_fetch:
                        try:
                            last_dt = datetime.fromisoformat(last_fetch)
                            due = (now - last_dt).total_seconds() >= interval
                        except ValueError:
                            due = True
                    if due:
                        self.queue_size += 1
                        self.broker and self.broker.publish(
                            "tick",
                            {
                                "target": target["value"],
                                "target_id": target["id"],
                                "scheduled_at": now.isoformat(),
                            },
                        )
                        try:
                            self.fetch_callback(target)
                            self.last_run = datetime.now(timezone.utc).isoformat()
                        finally:
                            self.queue_size = max(0, self.queue_size - 1)
            except Exception as exc:  # noqa: BLE001 - wir loggen und laufen weiter
                self.logger.exception("Scheduler-Fehler: %s", exc)
                self.broker and self.broker.publish("error", {"message": str(exc)})
            time.sleep(self.poll_interval)


def create_app() -> Flask:
    """Erzeugt und konfiguriert die Flask-App."""

    config = _ensure_config_file()
    logger = _setup_logging(config["log_path"])
    storage = Storage(config["storage_path"])

    # Vorkonfigurierte Targets beim ersten Start in die DB schreiben.
    if not storage.get_targets():
        for target in config.get("targets", []):
            storage.add_target(target["type"], target["value"], target["poll_interval_seconds"])

    broker = EventBroker() if config.get("enable_sse", True) else None
    client = NitterClient(
        instances=config["nitter_instances"],
        user_agent=config["user_agent"],
        max_requests_per_minute=config["max_requests_per_instance_per_minute"],
        backoff_base_seconds=config["backoff_base_seconds"],
        logger=logger,
    )

    app = Flask(__name__, static_folder=str((APP_ROOT / ".." / "frontend").resolve()), static_url_path="")
    CORS(app)

    state = {
        "last_run": None,
    }

    def _store_entries(target_row, entries: List[Dict], instance: Optional[str]) -> int:
        new_count = 0
        for entry in entries:
            tweet_id = str(entry.get("id") or entry.get("link"))
            content = entry.get("title") or entry.get("summary") or ""
            created_at = entry.get("published") or datetime.now(timezone.utc).isoformat()
            raw = entry.get("raw", entry)
            if not tweet_id:
                continue
            stored = storage.upsert_tweet(
                tweet_id=tweet_id,
                target=f"{target_row['type']}:{target_row['value']}",
                content=content,
                created_at=created_at,
                raw=raw,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                instance=instance or "",
            )
            if stored:
                new_count += 1
                if broker:
                    broker.publish(
                        "new_tweet",
                        {
                            "target": target_row["value"],
                            "target_id": target_row["id"],
                            "tweet_id": tweet_id,
                            "created_at": created_at,
                        },
                    )
        keep_limit = config.get("keep_only_last_n_per_target")
        if keep_limit:
            storage.prune_old_entries(int(keep_limit))
        return new_count

    def _fetch_target(target_row) -> Dict:
        entries, instance, error = client.fetch_target(target_row["type"], target_row["value"])
        now_iso = datetime.now(timezone.utc).isoformat()
        if error:
            logger.warning("Fehler beim Abruf von %s: %s", target_row["value"], error)
            if broker:
                broker.publish(
                    "error",
                    {
                        "target": target_row["value"],
                        "message": error,
                        "instance": instance,
                    },
                )
            return {"target": target_row["value"], "new": 0, "error": error, "instance": instance}
        new_count = _store_entries(target_row, entries, instance)
        storage.update_target_fetch_state(target_row["id"], entries[0]["id"] if entries else None, now_iso)
        state["last_run"] = now_iso
        if broker:
            broker.publish(
                "cooldown",
                {
                    "target": target_row["value"],
                    "next_run_in": target_row["poll_interval_seconds"],
                },
            )
        return {"target": target_row["value"], "new": new_count, "error": None, "instance": instance}

    scheduler = Scheduler(storage=storage, fetch_callback=_fetch_target, broker=broker, logger=logger)
    scheduler.start()

    @app.route("/")
    def index() -> Response:
        return app.send_static_file("index.html")

    @app.route("/api/config", methods=["GET"])
    def api_config() -> Response:
        public_config = dict(config)
        return jsonify(public_config)

    @app.route("/api/targets", methods=["GET"])
    def api_targets() -> Response:
        targets = [dict(row) for row in storage.get_targets()]
        return jsonify(targets)

    @app.route("/api/targets", methods=["POST"])
    def api_targets_create() -> Response:
        payload = request.get_json(force=True)
        target_type = payload.get("type")
        value = (payload.get("value") or "").strip()
        poll_interval = int(payload.get("poll_interval_seconds") or 300)
        if target_type not in {"user", "hashtag"}:
            return jsonify({"error": "type muss user oder hashtag sein"}), 400
        if not value:
            return jsonify({"error": "value darf nicht leer sein"}), 400
        if poll_interval < 60:
            return jsonify({"error": "poll_interval_seconds muss >= 60 sein"}), 400
        new_id = storage.add_target(target_type, value, poll_interval)
        broker and broker.publish(
            "tick",
            {"target": value, "target_id": new_id, "scheduled_at": datetime.now(timezone.utc).isoformat()},
        )
        return jsonify({"id": new_id, "type": target_type, "value": value, "poll_interval_seconds": poll_interval})

    @app.route("/api/targets/<int:target_id>", methods=["DELETE"])
    def api_targets_delete(target_id: int) -> Response:
        if not storage.get_target(target_id):
            return jsonify({"error": "Target nicht gefunden"}), 404
        storage.delete_target(target_id)
        broker and broker.publish("cooldown", {"target": target_id, "deleted": True})
        return jsonify({"status": "deleted"})

    @app.route("/api/fetch/once", methods=["POST"])
    def api_fetch_once() -> Response:
        targets = storage.get_targets()
        summary = {"newCountsByTarget": {}, "failedInstances": []}
        for target in targets:
            result = _fetch_target(target)
            summary["newCountsByTarget"][target["value"]] = result["new"]
            if result["error"]:
                summary["failedInstances"].append(
                    {"instance": result["instance"], "error": result["error"], "target": target["value"]}
                )
        return jsonify(summary)

    @app.route("/api/tweets", methods=["GET"])
    def api_tweets() -> Response:
        target = request.args.get("target")
        limit = int(request.args.get("limit", 50))
        query = request.args.get("q")
        rows = storage.get_tweets(target, limit, query)
        tweets = []
        for row in rows:
            tweet = dict(row)
            try:
                tweet["raw"] = json.loads(tweet["raw"])
            except Exception:  # noqa: BLE001 - Fallback
                tweet["raw"] = {}
            tweets.append(tweet)
        return jsonify(tweets)

    @app.route("/api/export.jsonl", methods=["GET"])
    def api_export() -> Response:
        def generate():
            for line in storage.export_tweets():
                yield line + "\n"

        headers = {"Content-Disposition": "attachment; filename=export.jsonl"}
        return Response(generate(), mimetype="application/jsonl", headers=headers)

    @app.route("/api/health", methods=["GET"])
    def api_health() -> Response:
        return jsonify(
            {
                "status": "ok",
                "rttByInstance": client.get_health_snapshot(),
                "queueSize": scheduler.queue_size,
                "lastRun": state["last_run"],
            }
        )

    @app.route("/api/stream", methods=["GET"])
    def api_stream() -> Response:
        if not broker:
            return Response("SSE deaktiviert", status=503)

        client_queue = broker.register()

        def event_stream():
            try:
                yield "event: hello\ndata: {}\n\n"
                while True:
                    try:
                        payload = client_queue.get(timeout=15)
                    except queue.Empty:
                        yield "event: heartbeat\ndata: {}\n\n"
                        continue
                    yield f"data: {payload}\n\n"
            finally:
                broker.unregister(client_queue)

        return Response(event_stream(), mimetype="text/event-stream")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5173, debug=False)
