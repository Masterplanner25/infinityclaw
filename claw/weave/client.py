"""WeaveClient — HTTP client for cross-node Weave communication."""
from __future__ import annotations
import asyncio
import logging
from typing import Any

import httpx

from .model import WeaveNode

logger = logging.getLogger(__name__)


class WeaveClient:
    def __init__(self, local_node_id: str, timeout: float = 10.0) -> None:
        self.local_node_id = local_node_id
        self.timeout = timeout

    def _headers(self, node: WeaveNode) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if node.api_key:
            h["Authorization"] = f"Bearer {node.api_key}"
        return h

    async def ping(self, node: WeaveNode) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{node.url.rstrip('/')}/health", headers=self._headers(node))
                return r.status_code == 200
        except Exception:
            return False

    async def list_agents(self, node: WeaveNode) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{node.url.rstrip('/')}/weave/agents",
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json().get("agents", [])
        except Exception as exc:
            logger.debug("list_agents failed for node %s: %s", node.node_id, exc)
            return []

    async def delegate(
        self,
        node: WeaveNode,
        agent_id: str,
        prompt: str,
        context: str = "",
        session_key: str = "",
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "from_node": self.local_node_id,
                    "agent_id": agent_id,
                    "prompt": prompt,
                    "context": context,
                    "session_key": session_key,
                }
                r = await client.post(
                    f"{node.url.rstrip('/')}/weave/delegate",
                    json=payload,
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json().get("response", "")
        except Exception as exc:
            logger.debug("delegate failed for node %s: %s", node.node_id, exc)
            return f"[error: weave delegate to {node.node_id} failed: {exc}]"

    async def fetch_documents(self, node: WeaveNode, agent_id: str) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/documents",
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json().get("documents", [])
        except Exception as exc:
            logger.debug("fetch_documents failed for node %s agent %s: %s", node.node_id, agent_id, exc)
            return []

    async def fetch_document(
        self, node: WeaveNode, agent_id: str, doc_id: str
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/documents/{doc_id}",
                    headers=self._headers(node),
                )
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.debug("fetch_document failed for node %s doc %s: %s", node.node_id, doc_id, exc)
            return None

    async def fetch_tasks(
        self, node: WeaveNode, agent_id: str, status: str = ""
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                params = {"status": status} if status else {}
                r = await client.get(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/tasks",
                    params=params,
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json().get("tasks", [])
        except Exception as exc:
            logger.debug("fetch_tasks failed for node %s agent %s: %s", node.node_id, agent_id, exc)
            return []

    async def list_all_agents(self, nodes: list[WeaveNode]) -> list[dict[str, Any]]:
        """Query all nodes concurrently and return a merged roster with node attribution."""
        if not nodes:
            return []
        results = await asyncio.gather(
            *[self.list_agents(n) for n in nodes], return_exceptions=True
        )
        merged = []
        for node, agents in zip(nodes, results):
            if isinstance(agents, list):
                for a in agents:
                    merged.append({"node_id": node.node_id, "node_url": node.url, **a})
        return merged

    async def create_document(
        self,
        node: WeaveNode,
        agent_id: str,
        name: str,
        body: str = "",
        content_type: str = "text",
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/documents",
                    json={"name": name, "body": body, "content_type": content_type},
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.debug("create_document failed for node %s: %s", node.node_id, exc)
            return None

    async def create_task(
        self,
        node: WeaveNode,
        agent_id: str,
        title: str,
        body: str = "",
        priority: int = 0,
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/tasks",
                    json={"title": title, "body": body, "priority": priority},
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.debug("create_task failed for node %s: %s", node.node_id, exc)
            return None

    async def update_task(
        self,
        node: WeaveNode,
        agent_id: str,
        task_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.patch(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/tasks/{task_id}",
                    json={k: v for k, v in fields.items() if v is not None},
                    headers=self._headers(node),
                )
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.debug("update_task failed for node %s task %s: %s", node.node_id, task_id, exc)
            return None

    async def search_knowledge(
        self,
        node: WeaveNode,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{node.url.rstrip('/')}/weave/workspace/{agent_id}/knowledge",
                    params={"q": query, "limit": limit},
                    headers=self._headers(node),
                )
                r.raise_for_status()
                return r.json().get("chunks", [])
        except Exception as exc:
            logger.debug("search_knowledge failed for node %s: %s", node.node_id, exc)
            return []

    async def register_self(self, remote: WeaveNode, self_node: WeaveNode) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "node_id": self_node.node_id,
                    "url": self_node.url,
                    "label": self_node.label,
                    "api_key": self_node.api_key,
                }
                r = await client.post(
                    f"{remote.url.rstrip('/')}/weave/nodes/register",
                    json=payload,
                    headers=self._headers(remote),
                )
                r.raise_for_status()
                return True
        except Exception as exc:
            logger.debug("register_self failed for node %s: %s", remote.node_id, exc)
            return False
