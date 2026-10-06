"""Retrieval cache backed by memory and a small SQLite file."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def make_cache_key(query: str, filters: dict[str, str], k: int) -> str:
    """Hash the rewritten query, filters, and k into a cache key."""
    payload = json.dumps(
        {"query": query, "filters": filters, "k": k},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class RetrievalCache:
    """TTL cache. A hit is returned without embedding or querying Chroma."""

    def __init__(
        self,
        path: Path,
        ttl_seconds: int = 3600,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._memory: dict[str, tuple[float, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, key: str) -> Any | None:
        """Return the cached payload, or None on a miss or expired entry."""
        now = self._clock()
        cached = self._memory.get(key)
        if cached is not None:
            created_at, payload = cached
            if now - created_at <= self.ttl_seconds:
                return payload
            self._memory.pop(key, None)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM retrieval_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        payload_raw, created_at = row
        if now - float(created_at) > self.ttl_seconds:
            self._delete(key)
            return None
        payload = json.loads(payload_raw)
        self._memory[key] = (float(created_at), payload)
        return payload

    def set(self, key: str, payload: Any) -> None:
        """Store a JSON payload in memory and in SQLite."""
        created_at = self._clock()
        self._memory[key] = (created_at, payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_cache (cache_key, payload, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    created_at = excluded.created_at
                """,
                (key, json.dumps(payload), created_at),
            )

    def _delete(self, key: str) -> None:
        self._memory.pop(key, None)
        with self._connect() as conn:
            conn.execute("DELETE FROM retrieval_cache WHERE cache_key = ?", (key,))

    def clear(self) -> None:
        """Remove every cached entry."""
        self._memory.clear()
        with self._connect() as conn:
            conn.execute("DELETE FROM retrieval_cache")

    def invalidate(self) -> None:
        """Drop the cache after ingest stores new chunks."""
        self.clear()
