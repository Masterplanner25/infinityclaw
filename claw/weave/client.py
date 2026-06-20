"""WeaveClient — HTTP client for cross-node Weave communication."""
from __future__ import annotations
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
