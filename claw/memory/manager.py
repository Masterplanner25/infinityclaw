"""MemoryManager — per-agent persistent memory backed by nodus_memory."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from nodus_memory import InMemoryStore, MemoryNode, recall_async
from nodus_memory.address import build_path
from nodus_memory.models import VALID_NODE_TYPES, VALID_MEMORY_TYPES
from nodus_memory.scoring import update_feedback

from claw.config.schema import MemoryConfig

if TYPE_CHECKING:
    from claw.aindy.client import _AsyncAINDYClient
    from claw.aindy.memory_store import AINDYMemoryStore

logger = logging.getLogger(__name__)

_DEFAULT_NODE_TYPE = "insight"
_DEFAULT_MEMORY_TYPE = "insight"
_NAMESPACE = "claw"


class MemoryManager:
    """Agent memory with pluggable storage backend.

    Backend selection (from MemoryConfig + AINDYConfig):
    - ``aindy.memory_backend = "aindy"``         →  AINDY MAS only (hard-fail on error)
    - ``aindy.memory_backend = "aindy-fallback"`` →  AINDY MAS with SQLite fallback
    - otherwise                                  →  local SQLite or InMemoryStore
    """

    def __init__(
        self,
        config: MemoryConfig,
        state_dir: str = "~/.claw",
        aindy_client: Optional["_AsyncAINDYClient"] = None,
        aindy_memory_backend: str = "local",
        aindy_user_id: str = "claw",
    ) -> None:
        self._config = config
        self._enabled = config.enabled
        self._aindy_backend = aindy_memory_backend  # "local" | "aindy" | "aindy-fallback"

        # Always initialise the local store — serves as fallback or primary.
        if self._enabled:
            db_path = config.db_path or str(Path(state_dir).expanduser() / "memory.db")
            if db_path == ":memory:":
                self._store = InMemoryStore()
                logger.info("[memory] using in-memory store")
            else:
                from claw.memory.sqlite_store import MemorySqliteStore
                self._store = MemorySqliteStore(db_path)
                logger.info("[memory] using SQLite store: %s", db_path)
        else:
            self._store = InMemoryStore()  # unused but satisfies type checker

        # AINDY store — active when aindy_client provided AND backend != "local"
        self._aindy_store: Optional["AINDYMemoryStore"] = None
        if (
            self._enabled
            and aindy_client is not None
            and aindy_memory_backend in ("aindy", "aindy-fallback")
        ):
            from claw.aindy.memory_store import AINDYMemoryStore
            fallback = self._store if aindy_memory_backend == "aindy-fallback" else None
            self._aindy_store = AINDYMemoryStore(
                aindy_client, user_id=aindy_user_id, fallback=fallback
            )
            logger.info(
                "[memory] AINDY MAS backend active user_id=%s mode=%s",
                aindy_user_id, aindy_memory_backend,
            )

    def is_enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------ #
    # Internal: run AINDY op with optional local fallback
    # ------------------------------------------------------------------ #

    async def _aindy_or_local(self, aindy_coro, local_fn):
        """Await aindy_coro; on exception fallback to local_fn() unless strict mode."""
        try:
            return await aindy_coro
        except Exception as exc:
            if self._aindy_backend == "aindy":
                raise
            logger.warning("[memory] AINDY error, falling back to local: %s", exc)
            return local_fn()

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    async def remember(
        self,
        agent_id: str,
        content: str,
        *,
        tags: Optional[list[str]] = None,
        node_type: str = _DEFAULT_NODE_TYPE,
        memory_type: str = _DEFAULT_MEMORY_TYPE,
        source: Optional[str] = None,
        execution_unit_id: Optional[str] = None,
    ) -> MemoryNode:
        """Store a new memory node and return it."""
        if not self._enabled:
            raise RuntimeError("Memory is disabled — set memory.enabled = true in claw.toml")

        node_type = node_type if node_type in VALID_NODE_TYPES else _DEFAULT_NODE_TYPE
        memory_type = memory_type if memory_type in VALID_MEMORY_TYPES else _DEFAULT_MEMORY_TYPE

        node_id = str(uuid.uuid4())
        extra: dict = {}
        if execution_unit_id:
            extra["execution_unit_id"] = execution_unit_id
        node = MemoryNode(
            id=node_id,
            content=content,
            tags=tags or [],
            node_type=node_type,
            user_id=agent_id,
            memory_type=memory_type,
            path=build_path("claw", _NAMESPACE, memory_type, node_id),
            namespace=_NAMESPACE,
            source=source,
            extra=extra,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        if self._aindy_store:
            await self._aindy_or_local(
                self._aindy_store.write(node),
                lambda: self._store.write(node),
            )
        else:
            self._store.write(node)

        logger.debug("[memory] agent=%s stored node_id=%s tags=%s", agent_id, node_id, tags)
        return node

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    async def recall(
        self,
        agent_id: str,
        query: str,
        *,
        tags: Optional[list[str]] = None,
        limit: int = 5,
    ) -> list[MemoryNode]:
        """Retrieve the most relevant memories for *query*."""
        if not self._enabled:
            return []
        try:
            if self._aindy_store:
                return await self._aindy_or_local(
                    self._aindy_store.search(query, agent_id, limit=limit, tags=tags),
                    lambda: [],  # local recall requires recall_async; don't mix
                )
            nodes = await recall_async(
                query=query,
                user_id=agent_id,
                store=self._store,
                limit=limit,
                tags=tags or None,
            )
            logger.debug(
                "[memory] agent=%s recall query=%r returned %d nodes",
                agent_id, query[:40], len(nodes),
            )
            return nodes
        except Exception as exc:
            logger.warning("[memory] recall error agent=%s: %s", agent_id, exc)
            return []

    async def list_all(self, agent_id: str, limit: int = 100) -> list[MemoryNode]:
        """Return all stored nodes for *agent_id* (most recent first)."""
        if not self._enabled:
            return []
        if self._aindy_store:
            return await self._aindy_or_local(
                self._aindy_store.list_nodes(agent_id, limit=limit),
                lambda: _local_list(self._store, agent_id, limit),
            )
        return _local_list(self._store, agent_id, limit)

    async def get(self, agent_id: str, node_id: str) -> Optional[MemoryNode]:
        if self._aindy_store:
            return await self._aindy_or_local(
                self._aindy_store.get_node(node_id, agent_id),
                lambda: self._store.get(node_id, agent_id),
            )
        return self._store.get(node_id, agent_id)

    # ------------------------------------------------------------------ #
    # Delete
    # ------------------------------------------------------------------ #

    async def forget(self, agent_id: str, node_id: str) -> bool:
        """Delete a memory node. Returns True if it existed."""
        if not self._enabled:
            return False
        if self._aindy_store:
            result = await self._aindy_or_local(
                self._aindy_store.delete_node(node_id, agent_id),
                lambda: self._store.delete(node_id, agent_id),
            )
            if result:
                logger.info("[memory] agent=%s deleted node_id=%s", agent_id, node_id)
            return bool(result)
        result = self._store.delete(node_id, agent_id)
        if result:
            logger.info("[memory] agent=%s deleted node_id=%s", agent_id, node_id)
        return result

    # ------------------------------------------------------------------ #
    # Feedback (weight adjustment — local store only for now)
    # ------------------------------------------------------------------ #

    def feedback(self, agent_id: str, node_id: str, *, success: bool) -> None:
        """Record success/failure feedback to adjust node weight."""
        if not self._enabled:
            return
        node = self._store.get(node_id, agent_id)
        if node:
            update_feedback(node, success)
            self._store.write(node)

    def close(self) -> None:
        """Close the underlying store connection (important on Windows)."""
        if hasattr(self._store, "close"):
            self._store.close()


def _local_list(store, agent_id: str, limit: int) -> list[MemoryNode]:
    nodes = store.list_by_user(agent_id, limit=limit)
    return sorted(nodes, key=lambda n: n.created_at, reverse=True)
