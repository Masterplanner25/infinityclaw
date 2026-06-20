"""MemorySqliteStore — sqlite3-backed MemoryStore satisfying nodus_memory.MemoryStore."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nodus_memory import MemoryNode

_DDL = """
CREATE TABLE IF NOT EXISTS memory_nodes (
    id          TEXT    NOT NULL,
    user_id     TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '[]',
    node_type   TEXT    NOT NULL DEFAULT 'insight',
    memory_type TEXT    NOT NULL DEFAULT 'insight',
    path        TEXT,
    namespace   TEXT,
    source      TEXT,
    impact_score REAL   NOT NULL DEFAULT 1.0,
    weight      REAL    NOT NULL DEFAULT 1.0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    usage_count INTEGER NOT NULL DEFAULT 0,
    embedding   TEXT,
    extra       TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_nodes(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_nodes(user_id, memory_type);
"""


class MemorySqliteStore:
    """Persistent sqlite3 backend for nodus_memory.

    Thread-safe via a per-connection lock. All methods are synchronous
    (matching the MemoryStore protocol).
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ------------------------------------------------------------------ #
    # MemoryStore protocol
    # ------------------------------------------------------------------ #

    def write(self, node: MemoryNode) -> MemoryNode:
        with self._lock:
            conn = self._connect()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO memory_nodes
                    (id, user_id, content, tags, node_type, memory_type, path, namespace,
                     source, impact_score, weight, success_count, failure_count,
                     usage_count, embedding, extra, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id, user_id) DO UPDATE SET
                    content=excluded.content,
                    tags=excluded.tags,
                    node_type=excluded.node_type,
                    memory_type=excluded.memory_type,
                    impact_score=excluded.impact_score,
                    weight=excluded.weight,
                    success_count=excluded.success_count,
                    failure_count=excluded.failure_count,
                    usage_count=excluded.usage_count,
                    embedding=excluded.embedding,
                    extra=excluded.extra,
                    updated_at=excluded.updated_at
                """,
                (
                    node.id, node.user_id, node.content,
                    json.dumps(node.tags), node.node_type, node.memory_type,
                    node.path, node.namespace, node.source,
                    node.impact_score, node.weight,
                    node.success_count, node.failure_count, node.usage_count,
                    json.dumps(node.embedding) if node.embedding else None,
                    json.dumps(node.extra),
                    node.created_at.isoformat() if node.created_at else now,
                    now,
                ),
            )
            conn.commit()
        return node

    def get(self, node_id: str, user_id: str) -> Optional[MemoryNode]:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM memory_nodes WHERE id=? AND user_id=?",
                (node_id, user_id),
            ).fetchone()
        return _row_to_node(row) if row else None

    def delete(self, node_id: str, user_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "DELETE FROM memory_nodes WHERE id=? AND user_id=?",
                (node_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_by_user(self, user_id: str, limit: int = 100) -> list[MemoryNode]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM memory_nodes WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_row_to_node(r) for r in rows]

    def search_by_tags(self, tags: list[str], user_id: str, limit: int = 20) -> list[MemoryNode]:
        """Return nodes that contain ANY of *tags*."""
        nodes = self.list_by_user(user_id, limit=1000)
        tag_set = set(tags)
        matched = [n for n in nodes if tag_set & set(n.tags)]
        return matched[:limit]

    def search_by_path(self, path_glob: str, user_id: str, limit: int = 20) -> list[MemoryNode]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM memory_nodes WHERE user_id=? AND path GLOB ? ORDER BY created_at DESC LIMIT ?",
                (user_id, path_glob, limit),
            ).fetchall()
        return [_row_to_node(r) for r in rows]

    def search_semantic(self, embedding: list[float], user_id: str, limit: int = 10) -> list[MemoryNode]:
        """Fallback: return most-recent nodes (no vector index in Phase 6)."""
        return self.list_by_user(user_id, limit=limit)

    def update_feedback(self, node_id: str, success: bool) -> None:
        with self._lock:
            conn = self._connect()
            if success:
                conn.execute(
                    "UPDATE memory_nodes SET success_count=success_count+1, weight=MIN(weight*1.05,10.0), updated_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), node_id),
                )
            else:
                conn.execute(
                    "UPDATE memory_nodes SET failure_count=failure_count+1, weight=MAX(weight*0.9,0.1), updated_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), node_id),
                )
            conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _row_to_node(row: sqlite3.Row) -> MemoryNode:
    return MemoryNode(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        tags=json.loads(row["tags"]),
        node_type=row["node_type"],
        memory_type=row["memory_type"],
        path=row["path"],
        namespace=row["namespace"],
        source=row["source"],
        impact_score=row["impact_score"],
        weight=row["weight"],
        success_count=row["success_count"],
        failure_count=row["failure_count"],
        usage_count=row["usage_count"],
        embedding=json.loads(row["embedding"]) if row["embedding"] else None,
        extra=json.loads(row["extra"]) if row["extra"] else {},
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
