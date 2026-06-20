"""Async wrapper around aindy_sdk.AINDYClient for use in async Claw code."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class _AsyncAINDYClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        from aindy_sdk import AINDYClient
        self._base_url = base_url.rstrip("/")
        self._sync = AINDYClient(base_url=base_url, api_key=api_key)

    async def emit_event(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.events.emit, event_type, payload)

    async def memory_write(self, path: str, content: str, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.memory.write, path, content, **kwargs)

    async def memory_read(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.memory.read, path, **kwargs)

    async def memory_search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.memory.search, query, **kwargs)

    async def memory_list(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.memory.list, path, **kwargs)

    async def submit_job(self, task_name: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.syscalls.call,
            "sys.v1.job.submit",
            {"task_name": task_name, "payload": payload, **kwargs},
        )

    async def sandbox_posture(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.sandbox.posture)

    async def ping(self) -> bool:
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(f"{self._base_url}/health")
            await asyncio.to_thread(urllib.request.urlopen, req, None, 5)
            return True
        except Exception:
            return False
