"""SqliteApiKeyStore — sqlite3-backed persistent API key storage."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nodus_auth.keys import generate_key, hash_key

from .store import ApiKeyRecord

_DDL = """
CREATE TABLE IF NOT EXISTS api_keys (
    key_id      TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    scopes      TEXT NOT NULL DEFAULT '*',
    created_at  TEXT NOT NULL,
    last_used   TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_keys_hash ON api_keys(key_hash);
"""


class SqliteApiKeyStore:
    """Persistent sqlite3 API key store.

    Drop-in replacement for in-memory ApiKeyStore.
    Thread-safe via a lock.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            self._connect().executescript(_DDL)
            self._connect().commit()

    # ------------------------------------------------------------------ #
    # Public API (mirrors ApiKeyStore)
    # ------------------------------------------------------------------ #

    def create(self, label: str, scopes: list[str] | None = None) -> tuple[str, ApiKeyRecord]:
        raw_key, key_hash = generate_key(prefix="claw_")
        key_id = raw_key.split("_")[1][:8] if "_" in raw_key else raw_key[:8]
        scope_str = ",".join(scopes or ["*"])
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._connect().execute(
                "INSERT INTO api_keys (key_id, key_hash, label, scopes, created_at) VALUES (?,?,?,?,?)",
                (key_id, key_hash, label, scope_str, now),
            )
            self._connect().commit()
        record = ApiKeyRecord(
            key_id=key_id,
            key_hash=key_hash,
            label=label,
            scopes=(scopes or ["*"]),
            created_at=datetime.fromisoformat(now),
        )
        return raw_key, record

    def verify(self, raw_key: str) -> Optional[ApiKeyRecord]:
        key_hash = hash_key(raw_key)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash=? AND enabled=1", (key_hash,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE api_keys SET last_used=? WHERE key_id=?", (now, row["key_id"]))
            conn.commit()
        return _row_to_record(row)

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            cur = self._connect().execute(
                "UPDATE api_keys SET enabled=0 WHERE key_id=?", (key_id,)
            )
            self._connect().commit()
            return cur.rowcount > 0

    def list_keys(self) -> list[ApiKeyRecord]:
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM api_keys WHERE enabled=1 ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get(self, key_id: str) -> Optional[ApiKeyRecord]:
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM api_keys WHERE key_id=?", (key_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _row_to_record(row: sqlite3.Row) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=row["key_id"],
        key_hash=row["key_hash"],
        label=row["label"],
        scopes=row["scopes"].split(",") if row["scopes"] else ["*"],
        created_at=_parse_dt(row["created_at"]),
        last_used=_parse_dt(row["last_used"]) if row["last_used"] else None,
        enabled=bool(row["enabled"]),
    )


def _parse_dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
