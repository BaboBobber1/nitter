"""HTTP-Client mit Instanzrotation für Nitter."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import feedparser
import requests


@dataclass
class InstanceState:
    """Hält Zustandsinformationen pro Nitter-Instanz."""

    base_url: str
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)
    backoff_until: float = 0.0
    consecutive_errors: int = 0
    last_rtt: Optional[float] = None
    last_error: Optional[str] = None


class NitterClient:
    """Kapselt HTTP-Zugriffe auf Nitter mit Round-Robin und Backoff."""

    def __init__(
        self,
        instances: List[str],
        user_agent: str,
        max_requests_per_minute: int,
        backoff_base_seconds: int,
        logger: logging.Logger,
    ) -> None:
        if not instances:
            raise ValueError("Mindestens eine Nitter-Instanz erforderlich.")
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.backoff_base_seconds = max(1, backoff_base_seconds)
        self._lock = threading.RLock()
        self._states: List[InstanceState] = [
            InstanceState(base_url=instance.rstrip("/"), tokens=max_requests_per_minute)
            for instance in instances
        ]
        self.max_requests_per_minute = max_requests_per_minute
        self._rotation_index = 0

    def _refill_tokens(self, state: InstanceState) -> None:
        now = time.monotonic()
        elapsed = now - state.last_refill
        tokens_to_add = (self.max_requests_per_minute / 60.0) * elapsed
        if tokens_to_add > 0:
            state.tokens = min(self.max_requests_per_minute, state.tokens + tokens_to_add)
            state.last_refill = now

    def _acquire_instance(self) -> Optional[InstanceState]:
        with self._lock:
            for _ in range(len(self._states)):
                state = self._states[self._rotation_index]
                self._rotation_index = (self._rotation_index + 1) % len(self._states)
                self._refill_tokens(state)
                now = time.monotonic()
                if now < state.backoff_until:
                    continue
                if state.tokens < 1:
                    continue
                state.tokens -= 1
                return state
        return None

    def _release_instance_on_error(self, state: InstanceState, status_code: Optional[int]) -> None:
        with self._lock:
            state.consecutive_errors += 1
            penalty = min(600, self.backoff_base_seconds * (2 ** (state.consecutive_errors - 1)))
            state.backoff_until = time.monotonic() + penalty
            state.last_error = f"HTTP {status_code}" if status_code else "Request-Fehler"
            self.logger.warning(
                "Instanz %s in Backoff für %ss nach Fehler %s",
                state.base_url,
                penalty,
                state.last_error,
            )

    def _release_instance_on_success(self, state: InstanceState, rtt: float) -> None:
        with self._lock:
            state.consecutive_errors = 0
            state.backoff_until = 0.0
            state.last_error = None
            state.last_rtt = rtt

    def _construct_url(self, state: InstanceState, target_type: str, value: str) -> str:
        if target_type == "user":
            path = f"/{value}/rss"
        else:
            path = f"/search/rss?f=tweets&q=%23{value}"
        return f"{state.base_url}{path}"

    def _fetch(self, url: str) -> Tuple[Optional[requests.Response], Optional[Exception]]:
        try:
            response = self.session.get(url, timeout=20)
            return response, None
        except Exception as exc:  # noqa: BLE001 - wir loggen und reichen weiter
            return None, exc

    def _parse_rss(self, response: requests.Response) -> List[Dict]:
        feed = feedparser.parse(response.content)
        entries: List[Dict] = []
        if feed.bozo:
            return entries
        for entry in feed.entries:
            tweet_id = getattr(entry, "id", None) or getattr(entry, "guid", None) or ""
            if not tweet_id:
                continue
            entries.append(
                {
                    "id": tweet_id,
                    "title": getattr(entry, "title", ""),
                    "summary": getattr(entry, "summary", ""),
                    "link": getattr(entry, "link", ""),
                    "published": getattr(entry, "published", ""),
                    "raw": entry,
                }
            )
        return entries

    def _parse_html(self, html: str) -> List[Dict]:
        entries: List[Dict] = []
        pattern = re.compile(r"/status/(\d+)")
        for match in pattern.finditer(html):
            tweet_id = match.group(1)
            # versuche den umgebenden Kontext zu finden
            start = max(0, match.start() - 200)
            excerpt = re.sub(r"\s+", " ", html[start : start + 400])
            entries.append(
                {
                    "id": tweet_id,
                    "title": "Tweet",
                    "summary": excerpt,
                    "link": tweet_id,
                    "published": "",
                    "raw": {"excerpt": excerpt},
                }
            )
        return entries

    def fetch_target(self, target_type: str, value: str) -> Tuple[List[Dict], Optional[str], Optional[str]]:
        """Liefert (Einträge, Instanz, Fehler)."""
        state = self._acquire_instance()
        if not state:
            return [], None, "Keine verfügbare Instanz (Rate-Limit oder Backoff)."
        url = self._construct_url(state, target_type, value)
        start = time.monotonic()
        response, error = self._fetch(url)
        rtt = time.monotonic() - start
        if error:
            self._release_instance_on_error(state, None)
            return [], state.base_url, str(error)
        if response is None:
            self._release_instance_on_error(state, None)
            return [], state.base_url, "Unbekannter Fehler"
        if response.status_code >= 400:
            self._release_instance_on_error(state, response.status_code)
            return [], state.base_url, f"HTTP {response.status_code}"

        entries = self._parse_rss(response)
        if not entries and "xml" not in response.headers.get("Content-Type", ""):
            entries = self._parse_html(response.text)
        self._release_instance_on_success(state, rtt)
        return entries, state.base_url, None

    def get_health_snapshot(self) -> List[Dict[str, object]]:
        """Gibt Zustandsdaten zu allen Instanzen zurück."""
        snapshot: List[Dict[str, object]] = []
        with self._lock:
            for state in self._states:
                snapshot.append(
                    {
                        "base_url": state.base_url,
                        "tokens": round(state.tokens, 2),
                        "backoff_remaining": max(0.0, state.backoff_until - time.monotonic()),
                        "consecutive_errors": state.consecutive_errors,
                        "last_rtt": state.last_rtt,
                        "last_error": state.last_error,
                    }
                )
        return snapshot


__all__ = ["NitterClient"]
