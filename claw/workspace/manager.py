"""WorkspaceManager — async interface over WorkspaceStore."""
from __future__ import annotations

import asyncio
from typing import Optional

from .model import Asset, Document, Task, Workspace, WorkspacePermission
from .store import WorkspaceStore


class WorkspaceManager:
    """Async manager for workspace objects (documents, tasks, assets, permissions).

    WorkspaceStore is synchronous (sqlite3); all methods wrap via asyncio.to_thread.
    Each agent's home workspace has id == agent_id and is created on first access.
    """

    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    def is_enabled(self) -> bool:
        return True

    def close(self) -> None:
        self._store.close()

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    async def ensure_workspace(self, agent_id: str, name: str = "") -> Workspace:
        """Get or create the home workspace for *agent_id*."""
        ws = await asyncio.to_thread(self._store.get_workspace, agent_id)
        if ws:
            return ws
        ws = Workspace(id=agent_id, name=name or agent_id, owner_agent_id=agent_id)
        return await asyncio.to_thread(self._store.create_workspace, ws)

    async def create_workspace(self, ws: Workspace) -> Workspace:
        return await asyncio.to_thread(self._store.create_workspace, ws)

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        return await asyncio.to_thread(self._store.get_workspace, workspace_id)

    async def list_workspaces(self) -> list[Workspace]:
        return await asyncio.to_thread(self._store.list_workspaces)

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    async def can_read(self, workspace_id: str, agent_id: str) -> bool:
        """Owner always has full access; others need an explicit read or write grant."""
        ws = await asyncio.to_thread(self._store.get_workspace, workspace_id)
        if ws and ws.owner_agent_id == agent_id:
            return True
        perm = await asyncio.to_thread(self._store.get_permission, workspace_id, agent_id)
        return perm is not None and perm.level in ("read", "write")

    async def can_write(self, workspace_id: str, agent_id: str) -> bool:
        ws = await asyncio.to_thread(self._store.get_workspace, workspace_id)
        if ws and ws.owner_agent_id == agent_id:
            return True
        perm = await asyncio.to_thread(self._store.get_permission, workspace_id, agent_id)
        return perm is not None and perm.level == "write"

    async def set_permission(self, perm: WorkspacePermission) -> None:
        await asyncio.to_thread(self._store.set_permission, perm)

    async def get_permission(
        self, workspace_id: str, agent_id: str
    ) -> Optional[WorkspacePermission]:
        return await asyncio.to_thread(self._store.get_permission, workspace_id, agent_id)

    async def list_permissions(self, workspace_id: str) -> list[WorkspacePermission]:
        return await asyncio.to_thread(self._store.list_permissions, workspace_id)

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    async def sync_document(self, doc: Document) -> Document:
        """ID-based upsert with last-write-wins (for Weave replication)."""
        return await asyncio.to_thread(self._store.sync_document, doc)

    async def upsert_document(self, doc: Document) -> Document:
        return await asyncio.to_thread(self._store.upsert_document, doc)

    async def get_document(self, doc_id: str) -> Optional[Document]:
        return await asyncio.to_thread(self._store.get_document, doc_id)

    async def list_documents(self, workspace_id: str) -> list[Document]:
        return await asyncio.to_thread(self._store.list_documents, workspace_id)

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    async def upsert_task(self, task: Task) -> Task:
        """ID-based upsert with last-write-wins (for Weave replication)."""
        return await asyncio.to_thread(self._store.upsert_task, task)

    async def create_task(self, task: Task) -> Task:
        return await asyncio.to_thread(self._store.create_task, task)

    async def get_task(self, task_id: str) -> Optional[Task]:
        return await asyncio.to_thread(self._store.get_task, task_id)

    async def update_task(self, task_id: str, **fields) -> Optional[Task]:
        return await asyncio.to_thread(self._store.update_task, task_id, **fields)

    async def list_tasks(
        self, workspace_id: str, status: Optional[str] = None
    ) -> list[Task]:
        return await asyncio.to_thread(self._store.list_tasks, workspace_id, status)

    # ------------------------------------------------------------------
    # Asset
    # ------------------------------------------------------------------

    async def create_asset(self, asset: Asset) -> Asset:
        return await asyncio.to_thread(self._store.create_asset, asset)

    async def list_assets(self, workspace_id: str) -> list[Asset]:
        return await asyncio.to_thread(self._store.list_assets, workspace_id)
