"""SQLite cache-first store. Every external call passes through `cached_call`, which is
the ONLY path to the network. A hit returns immediately (no network, no rate-limit sleep);
a miss acquires the rate limiter, fetches, and persists the result — including 404s, which
are stored as first-class rows so a renamed handle is recorded rather than silently lost.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .model import FetchError, PublicationNotFound


@dataclass
class CacheRow:
    cache_key: str
    url: str
    fetched_at: str
    status: str
    payload: object


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Cache:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        # WAL mode lets a background crawler write while the web server reads concurrently.
        # synchronous=NORMAL is safe with WAL (no corruption on crash) and far faster than FULL.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS http_cache (
                cache_key   TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                fetched_at  TEXT NOT NULL,
                status      TEXT NOT NULL,
                payload_json TEXT
            )
            """
        )
        self.conn.commit()

    def get(self, cache_key: str) -> CacheRow | None:
        cur = self.conn.execute(
            "SELECT cache_key, url, fetched_at, status, payload_json FROM http_cache WHERE cache_key = ?",
            (cache_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"]) if row["payload_json"] is not None else None
        return CacheRow(row["cache_key"], row["url"], row["fetched_at"], row["status"], payload)

    def put(self, cache_key: str, url: str, status: str, payload: object) -> CacheRow:
        payload_json = json.dumps(payload) if payload is not None else None
        fetched_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO http_cache (cache_key, url, fetched_at, status, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (cache_key, url, fetched_at, status, payload_json),
        )
        self.conn.commit()
        return CacheRow(cache_key, url, fetched_at, status, payload)

    def cached_call(self, cache_key: str, url: str, fetch_fn: Callable[[], object], rate_limiter) -> CacheRow:
        """Return the cached row if present; otherwise rate-limit, fetch, persist, return.

        A `PublicationNotFound` becomes a cached `http_404` row (payload None); any other
        error becomes a cached `error` row. Either way the failure is recorded, not raised,
        so a re-run hits the cache instead of re-hammering the endpoint.
        """
        existing = self.get(cache_key)
        if existing is not None:
            return existing

        rate_limiter.acquire()
        try:
            payload = fetch_fn()
            status = "ok"
        except PublicationNotFound:
            payload, status = None, "http_404"
        except (FetchError, Exception):  # noqa: BLE001 - record any failure, do not crash the crawl
            payload, status = None, "error"
        return self.put(cache_key, url, status, payload)

    def iter_prefix(self, prefix: str) -> Iterator[CacheRow]:
        cur = self.conn.execute(
            "SELECT cache_key, url, fetched_at, status, payload_json FROM http_cache "
            "WHERE cache_key LIKE ? ORDER BY cache_key",
            (prefix + "%",),
        )
        for row in cur.fetchall():
            payload = json.loads(row["payload_json"]) if row["payload_json"] is not None else None
            yield CacheRow(row["cache_key"], row["url"], row["fetched_at"], row["status"], payload)

    def close(self) -> None:
        self.conn.close()
