"""ChannelAdapterRegistry — owns and manages all active channel adapters."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nodus_adapter_base import BaseChannelAdapter

logger = logging.getLogger(__name__)


class ChannelAdapterRegistry:
    """Registers channel adapters and manages their lifecycle."""

    def __init__(self) -> None:
        self._adapters: dict[str, BaseChannelAdapter] = {}

    def register(self, adapter: BaseChannelAdapter) -> None:
        self._adapters[adapter.channel_id] = adapter
        logger.info("[channels] registered adapter channel_id=%s", adapter.channel_id)

    def get(self, channel_id: str) -> Optional[BaseChannelAdapter]:
        return self._adapters.get(channel_id)

    def all(self) -> list[BaseChannelAdapter]:
        return list(self._adapters.values())

    async def connect_all(self) -> None:
        results = await asyncio.gather(
            *[a.connect() for a in self._adapters.values()],
            return_exceptions=True,
        )
        for adapter, result in zip(self._adapters.values(), results):
            if isinstance(result, Exception):
                logger.error("[channels] %s failed to connect: %s", adapter.channel_id, result)

    async def disconnect_all(self) -> None:
        results = await asyncio.gather(
            *[a.disconnect() for a in self._adapters.values()],
            return_exceptions=True,
        )
        for adapter, result in zip(self._adapters.values(), results):
            if isinstance(result, Exception):
                logger.warning("[channels] %s disconnect error: %s", adapter.channel_id, result)

    async def send(self, channel_id: str, content: str, peer_id: str, **kwargs) -> None:
        adapter = self._adapters.get(channel_id)
        if adapter is None:
            logger.warning("[channels] no adapter for channel=%s", channel_id)
            return
        await adapter.send(content, peer_id, **kwargs)
