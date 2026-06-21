"""SQLite-backed workspace object store (sync, like MemorySqliteStore)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .model import Asset, Document, Task, Workspace, WorkspacePermission

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

_ISO = "%Y-%m-%dT%H:%M:%S.%f"


def _ts(d: datetime) -> str:
    return d.strftime(_ISO)


def _dt(s: str) -> datetime:
    return datetime.strptime(s, _ISO)


class WorkspaceStore:
    """SQLite store for workspace objects.

    Tables: workspaces, ws_documents, ws_tasks, ws_assets, ws_permissions.
    Pass db_path=":memory:" in tests.
    """

    def __init__(self, db_path: str) -> None:
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            p = Path(db_path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(p), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                description     TEXT NOT NULL DEFAULT '',
                owner_agent_id  TEXT NOT NULL,
                created_at      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ws_documents (
                id              TEXT PRIMARY KEY,
                workspace_id    TEXT NOT NULL,
                name            TEXT NOT NULL,
                content_type    TEXT NOT NULL DEFAULT 'text',
                body            TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_wsd_ws ON ws_documents(workspace_id);
            CREATE TABLE IF NOT EXISTS ws_tasks (
                id              TEXT PRIMARY KEY,
                workspace_id    TEXT NOT NULL,
                title           TEXT NOT NULL,
                body            TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'open',
                priority        INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_wst_ws ON ws_tasks(workspace_id);
            CREATE TABLE IF NOT EXISTS ws_assets (
                id              TEXT PRIMARY KEY,
                workspace_id    TEXT NOT NULL,
                name            TEXT NOT NULL,
                content_type    TEXT NOT NULL DEFAULT 'binary',
                path            TEXT NOT NULL DEFAULT '',
                size_bytes      INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_wsa_ws ON ws_assets(workspace_id);
            CREATE TABLE IF NOT EXISTS ws_permissions (
                workspace_id    TEXT NOT NULL,
                agent_id        TEXT NOT NULL,
                level           TEXT NOT NULL DEFAULT 'read',
                PRIMARY KEY (workspace_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
        """)
        self._conn.commit()
        current = _read_schema_version(self._conn)
        if current < SCHEMA_VERSION:
            _write_schema_version(self._conn, SCHEMA_VERSION)

    def schema_version(self) -> int:
        return _read_schema_version(self._conn)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def create_workspace(self, ws: Workspace) -> Workspace:
        self._conn.execute(
            "INSERT OR IGNORE INTO workspaces (id, name, description, owner_agent_id, created_at)"
            " VALUES (?,?,?,?,?)",
            (ws.id, ws.name, ws.description, ws.owner_agent_id, _ts(ws.created_at)),
        )
        self._conn.commit()
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if not row:
            return None
        return Workspace(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            owner_agent_id=row["owner_agent_id"],
            created_at=_dt(row["created_at"]),
        )

    def list_workspaces(self) -> list[Workspace]:
        rows = self._conn.execute(
            "SELECT * FROM workspaces ORDER BY created_at DESC"
        ).fetchall()
        return [
            Workspace(
                id=r["id"],
                name=r["name"],
                description=r["description"],
                owner_agent_id=r["owner_agent_id"],
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def sync_document(self, doc: Document) -> Document:
        """ID-based upsert with last-write-wins by updated_at (used by Weave sync)."""
        existing = self.get_document(doc.id)
        if existing is not None:
            if doc.updated_at <= existing.updated_at:
                return existing
            self._conn.execute(
                "UPDATE ws_documents SET name=?, content_type=?, body=?, updated_at=? WHERE id=?",
                (doc.name, doc.content_type, doc.body, _ts(doc.updated_at), doc.id),
            )
            self._conn.commit()
            return self.get_document(doc.id) or doc
        self._conn.execute(
            "INSERT INTO ws_documents (id, workspace_id, name, content_type, body, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (doc.id, doc.workspace_id, doc.name, doc.content_type, doc.body,
             _ts(doc.created_at), _ts(doc.updated_at)),
        )
        self._conn.commit()
        return doc

    def upsert_document(self, doc: Document) -> Document:
        existing = self._conn.execute(
            "SELECT id FROM ws_documents WHERE workspace_id = ? AND name = ?",
            (doc.workspace_id, doc.name),
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE ws_documents SET body = ?, content_type = ?, updated_at = ? WHERE id = ?",
                (doc.body, doc.content_type, _ts(doc.updated_at), existing["id"]),
            )
            self._conn.commit()
            updated = self.get_document(existing["id"])
            return updated if updated else doc
        self._conn.execute(
            "INSERT INTO ws_documents (id, workspace_id, name, content_type, body, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (doc.id, doc.workspace_id, doc.name, doc.content_type, doc.body,
             _ts(doc.created_at), _ts(doc.updated_at)),
        )
        self._conn.commit()
        return doc

    def get_document(self, doc_id: str) -> Optional[Document]:
        row = self._conn.execute(
            "SELECT * FROM ws_documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return None
        return Document(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            content_type=row["content_type"],
            body=row["body"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def list_documents(self, workspace_id: str) -> list[Document]:
        rows = self._conn.execute(
            "SELECT * FROM ws_documents WHERE workspace_id = ? ORDER BY updated_at DESC",
            (workspace_id,),
        ).fetchall()
        return [
            Document(
                id=r["id"],
                workspace_id=r["workspace_id"],
                name=r["name"],
                content_type=r["content_type"],
                body=r["body"],
                created_at=_dt(r["created_at"]),
                updated_at=_dt(r["updated_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    def upsert_task(self, task: Task) -> Task:
        """ID-based upsert with last-write-wins by updated_at (used by Weave sync)."""
        existing = self.get_task(task.id)
        if existing is not None:
            if task.updated_at <= existing.updated_at:
                return existing
            self._conn.execute(
                "UPDATE ws_tasks SET title=?, body=?, status=?, priority=?, updated_at=? WHERE id=?",
                (task.title, task.body, task.status, task.priority, _ts(task.updated_at), task.id),
            )
            self._conn.commit()
            return self.get_task(task.id) or task
        self._conn.execute(
            "INSERT INTO ws_tasks (id, workspace_id, title, body, status, priority, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (task.id, task.workspace_id, task.title, task.body,
             task.status, task.priority, _ts(task.created_at), _ts(task.updated_at)),
        )
        self._conn.commit()
        return task

    def create_task(self, task: Task) -> Task:
        self._conn.execute(
            "INSERT INTO ws_tasks (id, workspace_id, title, body, status, priority, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (task.id, task.workspace_id, task.title, task.body,
             task.status, task.priority, _ts(task.created_at), _ts(task.updated_at)),
        )
        self._conn.commit()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        row = self._conn.execute(
            "SELECT * FROM ws_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return Task(
            id=row["id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            body=row["body"],
            status=row["status"],
            priority=row["priority"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def update_task(self, task_id: str, **fields) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None
        allowed = {"title", "body", "status", "priority"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return task
        updates["updated_at"] = _ts(datetime.utcnow())
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        self._conn.execute(f"UPDATE ws_tasks SET {set_clause} WHERE id = ?", values)
        self._conn.commit()
        return self.get_task(task_id)

    def list_tasks(self, workspace_id: str, status: Optional[str] = None) -> list[Task]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM ws_tasks WHERE workspace_id = ? AND status = ?"
                " ORDER BY priority DESC, created_at DESC",
                (workspace_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM ws_tasks WHERE workspace_id = ?"
                " ORDER BY priority DESC, created_at DESC",
                (workspace_id,),
            ).fetchall()
        return [
            Task(
                id=r["id"],
                workspace_id=r["workspace_id"],
                title=r["title"],
                body=r["body"],
                status=r["status"],
                priority=r["priority"],
                created_at=_dt(r["created_at"]),
                updated_at=_dt(r["updated_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Asset
    # ------------------------------------------------------------------

    def create_asset(self, asset: Asset) -> Asset:
        self._conn.execute(
            "INSERT OR IGNORE INTO ws_assets"
            " (id, workspace_id, name, content_type, path, size_bytes, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (asset.id, asset.workspace_id, asset.name, asset.content_type,
             asset.path, asset.size_bytes, _ts(asset.created_at)),
        )
        self._conn.commit()
        return asset

    def list_assets(self, workspace_id: str) -> list[Asset]:
        rows = self._conn.execute(
            "SELECT * FROM ws_assets WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        ).fetchall()
        return [
            Asset(
                id=r["id"],
                workspace_id=r["workspace_id"],
                name=r["name"],
                content_type=r["content_type"],
                path=r["path"],
                size_bytes=r["size_bytes"],
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def set_permission(self, perm: WorkspacePermission) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ws_permissions (workspace_id, agent_id, level)"
            " VALUES (?,?,?)",
            (perm.workspace_id, perm.agent_id, perm.level),
        )
        self._conn.commit()

    def get_permission(self, workspace_id: str, agent_id: str) -> Optional[WorkspacePermission]:
        row = self._conn.execute(
            "SELECT * FROM ws_permissions WHERE workspace_id = ? AND agent_id = ?",
            (workspace_id, agent_id),
        ).fetchone()
        if not row:
            return None
        return WorkspacePermission(
            workspace_id=row["workspace_id"],
            agent_id=row["agent_id"],
            level=row["level"],
        )

    def list_permissions(self, workspace_id: str) -> list[WorkspacePermission]:
        rows = self._conn.execute(
            "SELECT * FROM ws_permissions WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return [
            WorkspacePermission(
                workspace_id=r["workspace_id"],
                agent_id=r["agent_id"],
                level=r["level"],
            )
            for r in rows
        ]
