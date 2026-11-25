import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DB_PATH = DATA_DIR / "cache.db"


class DiskCache:
    """Lightweight SQLite key-value cache with TTL support."""

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            value_json, expires_at = row
            if expires_at < now:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            return json.loads(value_json)

    def set(self, key: str, value: Any, ttl_seconds: int = 21600) -> None:
        expires_at = time.time() + ttl_seconds
        payload = json.dumps(value, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache (key, value, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at
                """,
                (key, payload, expires_at),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()


cache = DiskCache()
