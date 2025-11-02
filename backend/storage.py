"""SQLite-Datenhaltung für den Nitter Web-Scraper."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Generator, List, Optional


class Storage:
    """Kapselt alle Lese- und Schreiboperationen auf der SQLite-Datenbank."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialise_schema()

    def _initialise_schema(self) -> None:
        """Erzeugt das Schema falls notwendig."""
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tweets (
                    id TEXT PRIMARY KEY,
                    target TEXT,
                    content TEXT,
                    created_at TEXT,
                    raw TEXT,
                    fetched_at TEXT,
                    instance TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT,
                    value TEXT,
                    poll_interval_seconds INTEGER,
                    last_fetched_id TEXT,
                    last_fetched_at TEXT
                )
                """
            )
            self._connection.commit()

    def add_target(self, target_type: str, value: str, poll_interval_seconds: int) -> int:
        """Legt einen neuen Target-Eintrag an und liefert dessen ID."""
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO targets(type, value, poll_interval_seconds)
                VALUES (?, ?, ?)
                """,
                (target_type, value, poll_interval_seconds),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def delete_target(self, target_id: int) -> None:
        """Entfernt ein Target dauerhaft."""
        with self._lock:
            self._connection.execute("DELETE FROM targets WHERE id = ?", (target_id,))
            self._connection.commit()

    def get_targets(self) -> List[sqlite3.Row]:
        """Gibt alle Targets zurück."""
        with self._lock:
            cursor = self._connection.execute(
                "SELECT id, type, value, poll_interval_seconds, last_fetched_id, last_fetched_at FROM targets ORDER BY id ASC"
            )
            return list(cursor.fetchall())

    def get_target(self, target_id: int) -> Optional[sqlite3.Row]:
        """Liest ein Target anhand der ID."""
        with self._lock:
            cursor = self._connection.execute(
                "SELECT id, type, value, poll_interval_seconds, last_fetched_id, last_fetched_at FROM targets WHERE id = ?",
                (target_id,),
            )
            return cursor.fetchone()

    def upsert_tweet(
        self,
        tweet_id: str,
        target: str,
        content: str,
        created_at: str,
        raw: Dict,
        fetched_at: str,
        instance: str,
    ) -> bool:
        """Speichert einen Tweet. Rückgabewert True bedeutet: neu gespeichert."""
        raw_json = json.dumps(raw, ensure_ascii=False)
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO tweets(id, target, content, created_at, raw, fetched_at, instance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tweet_id, target, content, created_at, raw_json, fetched_at, instance),
            )
            self._connection.commit()
            return cursor.rowcount > 0

    def update_target_fetch_state(
        self,
        target_id: int,
        last_fetched_id: Optional[str],
        last_fetched_at: Optional[str],
    ) -> None:
        """Aktualisiert Metadaten eines Targets nach einem Fetch."""
        with self._lock:
            self._connection.execute(
                """
                UPDATE targets
                SET last_fetched_id = ?, last_fetched_at = ?
                WHERE id = ?
                """,
                (last_fetched_id, last_fetched_at, target_id),
            )
            self._connection.commit()

    def get_tweets(
        self,
        target: Optional[str] = None,
        limit: int = 50,
        query: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        """Liefert Tweets nach optionalem Target- und Suchfilter."""
        sql = "SELECT id, target, content, created_at, raw, fetched_at, instance FROM tweets"
        conditions: List[str] = []
        params: List[str] = []
        if target:
            conditions.append("target = ?")
            params.append(target)
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY datetime(created_at) DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            cursor = self._connection.execute(sql, tuple(params))
            return list(cursor.fetchall())

    def export_tweets(self) -> Generator[str, None, None]:
        """Erzeugt JSONL-Strings aller Tweets."""
        with self._lock:
            cursor = self._connection.execute(
                "SELECT id, target, content, created_at, raw, fetched_at, instance FROM tweets ORDER BY datetime(created_at) DESC"
            )
            for row in cursor:
                data = {
                    "id": row["id"],
                    "target": row["target"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "raw": json.loads(row["raw"] or "{}"),
                    "fetched_at": row["fetched_at"],
                    "instance": row["instance"],
                }
                yield json.dumps(data, ensure_ascii=False)

    def prune_old_entries(self, max_per_target: int) -> None:
        """Begrenzt die Anzahl gespeicherter Tweets pro Target."""
        with self._lock:
            cursor = self._connection.execute("SELECT DISTINCT target FROM tweets")
            targets = [row[0] for row in cursor.fetchall()]
            for target in targets:
                self._connection.execute(
                    """
                    DELETE FROM tweets
                    WHERE id NOT IN (
                        SELECT id FROM tweets WHERE target = ? ORDER BY datetime(created_at) DESC LIMIT ?
                    ) AND target = ?
                    """,
                    (target, max_per_target, target),
                )
            self._connection.commit()

    def close(self) -> None:
        """Schließt die Verbindung sauber."""
        with self._lock:
            self._connection.close()


__all__ = ["Storage"]
