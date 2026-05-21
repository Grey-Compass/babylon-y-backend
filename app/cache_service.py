from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DB_PATH = BASE_DIR / "babylon_y_cache.db"


def initialize_cache_db() -> None:
    with sqlite3.connect(CACHE_DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )
            """
        )
        connection.commit()


def get_cached_json(cache_key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    initialize_cache_db()

    with sqlite3.connect(CACHE_DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT payload_json, fetched_at
            FROM api_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

    if not row:
        return None

    payload_json, fetched_at = row
    if time.time() - float(fetched_at) > ttl_seconds:
        return None

    return json.loads(payload_json)


def get_stale_cached_json(cache_key: str) -> Optional[Dict[str, Any]]:
    initialize_cache_db()

    with sqlite3.connect(CACHE_DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT payload_json
            FROM api_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

    if not row:
        return None

    return json.loads(row[0])


def set_cached_json(cache_key: str, payload: Dict[str, Any]) -> None:
    initialize_cache_db()

    with sqlite3.connect(CACHE_DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO api_cache (cache_key, payload_json, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                fetched_at = excluded.fetched_at
            """,
            (
                cache_key,
                json.dumps(payload),
                time.time(),
            ),
        )
        connection.commit()
