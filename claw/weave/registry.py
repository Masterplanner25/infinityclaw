"""WeaveNodeStore — SQLite registry of peer Weave nodes."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional

from .model import WeaveNode

SCHEMA_VERSION = 1


def _read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def _write_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


class WeaveNodeStore:
    def __init__(self, db_path: str = "") -> None:
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            path = Path(db_path) if db_path else Path.home() / ".claw" / "weave.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS weave_nodes (
                node_id TEXT PRIMARY KEY,
                url     TEXT NOT NULL,
                label   TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
        """)
        self._conn.commit()
        current = _read_schema_version(self._conn)
        if current < SCHEMA_VERSION:
            _write_schema_version(self._conn, SCHEMA_VERSION)

    def schema_version(self) -> int:
        return _read_schema_version(self._conn)

    def register(self, node: WeaveNode) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO weave_nodes (node_id, url, label, api_key) VALUES (?,?,?,?)",
            (node.node_id, node.url, node.label, node.api_key),
        )
        self._conn.commit()

    def get(self, node_id: str) -> Optional[WeaveNode]:
        row = self._conn.execute(
            "SELECT node_id, url, label, api_key FROM weave_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return WeaveNode(node_id=row[0], url=row[1], label=row[2], api_key=row[3])

    def list_nodes(self) -> list[WeaveNode]:
        rows = self._conn.execute(
            "SELECT node_id, url, label, api_key FROM weave_nodes ORDER BY node_id"
        ).fetchall()
        return [WeaveNode(node_id=r[0], url=r[1], label=r[2], api_key=r[3]) for r in rows]

    def remove(self, node_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM weave_nodes WHERE node_id = ?", (node_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
