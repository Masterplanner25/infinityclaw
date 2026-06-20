"""AINDYMemoryStore — async AINDY MAS backend for MemoryManager.

MAS path convention: /memory/{user_id}/claw/{agent_id}/{node_type}/{node_id}

This is NOT a sync MemoryStore implementor. MemoryManager calls its async
methods directly, bypassing the sync MemoryStore protocol used by local backends.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from nodus_memory import MemoryNode

if TYPE_CHECKING:
    from claw.aindy.client import _AsyncAINDYClient

logger = logging.getLogger(__name__)


async def _fire_event(client: "_AsyncAINDYClient", event_type: str, payload: dict) -> None:
    try:
        await client.emit_event(event_type, payload)
    except Exception as exc:
        logger.debug("[aindy_memory] event skipped %s: %s", event_type, exc)

_NAMESPACE = "claw"


class AINDYMemoryStore:
    """Async AINDY MAS memory backend.

    Args:
        client: Async AINDY client instance.
        user_id: MAS identity root (single-user: "claw"; multi-user: JWT sub).
        fallback: Optional sync MemoryStore used in aindy-fallback mode.
    """

    def __init__(
        self,
        client: "_AsyncAINDYClient",
        user_id: str = "claw",
        fallback: Optional[object] = None,
    ) -> None:
        self._client = client
        self._user_id = user_id
        self._fallback = fallback

    # ------------------------------------------------------------------ #
    # Path helpers
    # ------------------------------------------------------------------ #

    def _node_path(self, agent_id: str, node_type: str, node_id: str) -> str:
        return f"/memory/{self._user_id}/{_NAMESPACE}/{agent_id}/{node_type}/{node_id}"

    def _scope_path(self, agent_id: str) -> str:
        return f"/memory/{self._user_id}/{_NAMESPACE}/{agent_id}/**"

    def _list_path(self, agent_id: str) -> str:
        return f"/memory/{self._user_id}/{_NAMESPACE}/{agent_id}/*"

    # ------------------------------------------------------------------ #
    # Async operations
    # ------------------------------------------------------------------ #

    async def write(self, node: MemoryNode) -> MemoryNode:
        path = self._node_path(node.user_id, node.node_type, node.id)
        payload = _node_to_dict(node)
        await self._client.memory_write(
            path,
            json.dumps(payload),
            tags=node.tags,
            node_id=node.id,
        )
        asyncio.create_task(_fire_event(self._client, "claw.memory.written", {
            "agent_id": node.user_id,
            "node_id": node.id,
            "path": path,
            "execution_unit_id": (node.extra or {}).get("execution_unit_id"),
        }))
        return node

    async def search(
        self,
        query: str,
        agent_id: str,
        limit: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[MemoryNode]:
        kwargs: dict = {"scope": self._scope_path(agent_id), "limit": limit}
        if tags:
            kwargs["tags"] = tags
        result = await self._client.memory_search(query, **kwargs)
        return _parse_nodes(result, agent_id)

    async def list_nodes(self, agent_id: str, limit: int = 100) -> list[MemoryNode]:
        result = await self._client.memory_list(self._list_path(agent_id), limit=limit)
        nodes = _parse_nodes(result, agent_id)
        return sorted(nodes, key=lambda n: n.created_at, reverse=True)

    async def get_node(self, node_id: str, agent_id: str) -> Optional[MemoryNode]:
        for node_type in ("insight", "decision", "outcome", "failure"):
            path = self._node_path(agent_id, node_type, node_id)
            try:
                result = await self._client.memory_read(path)
                nodes = _parse_nodes(result, agent_id)
                if nodes:
                    return nodes[0]
            except Exception:
                continue
        return None

    async def delete_node(self, node_id: str, agent_id: str) -> bool:
        # Try each possible node_type path.  KeyError / LookupError means "not
        # found at this path" — keep trying.  Any other exception (connectivity,
        # auth) is re-raised so the caller's fallback logic can handle it.
        last_connectivity_exc: Exception | None = None
        for node_type in ("insight", "decision", "outcome", "failure"):
            path = self._node_path(agent_id, node_type, node_id)
            try:
                await self._client.memory_delete(path)
                return True
            except (KeyError, LookupError):
                continue
            except Exception as exc:
                last_connectivity_exc = exc
                continue
        if last_connectivity_exc is not None:
            raise last_connectivity_exc
        return False


# ------------------------------------------------------------------ #
# Serialization helpers
# ------------------------------------------------------------------ #

def _node_to_dict(node: MemoryNode) -> dict:
    return {
        "id": node.id,
        "content": node.content,
        "tags": node.tags,
        "node_type": node.node_type,
        "memory_type": node.memory_type,
        "namespace": node.namespace,
        "source": node.source,
        "impact_score": node.impact_score,
        "weight": node.weight,
        "success_count": node.success_count,
        "failure_count": node.failure_count,
        "usage_count": node.usage_count,
        "extra": node.extra or {},
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def _parse_nodes(result: object, agent_id: str) -> list[MemoryNode]:
    """Convert an AINDY memory response to a list of MemoryNode."""
    if not isinstance(result, dict):
        return []

    # AINDY returns {nodes:[...]}, {data:[...]}, {results:[...]}, or a single node
    items: list = (
        result.get("nodes")
        or result.get("data")
        or result.get("results")
        or []
    )
    if not items and "content" in result:
        items = [result]

    nodes: list[MemoryNode] = []
    for item in items:
        try:
            raw_content = item.get("content", "{}")
            if isinstance(raw_content, str):
                try:
                    data = json.loads(raw_content)
                except json.JSONDecodeError:
                    data = {"content": raw_content}
            elif isinstance(raw_content, dict):
                data = raw_content
            else:
                data = {"content": str(raw_content)}

            nodes.append(MemoryNode(
                id=data.get("id") or item.get("node_id") or str(uuid.uuid4()),
                user_id=agent_id,
                content=data.get("content", ""),
                tags=data.get("tags") or [],
                node_type=data.get("node_type", "insight"),
                memory_type=data.get("memory_type", "insight"),
                namespace=data.get("namespace", _NAMESPACE),
                source=data.get("source"),
                impact_score=float(data.get("impact_score", 1.0)),
                weight=float(data.get("weight", 1.0)),
                success_count=int(data.get("success_count", 0)),
                failure_count=int(data.get("failure_count", 0)),
                usage_count=int(data.get("usage_count", 0)),
                extra=data.get("extra") or {},
                created_at=_parse_dt(data.get("created_at")),
                updated_at=datetime.now(timezone.utc),
            ))
        except Exception as exc:
            logger.debug("[aindy_memory] skipping malformed node: %s", exc)

    return nodes


def _parse_dt(value: object) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
