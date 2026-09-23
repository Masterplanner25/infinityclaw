"""ChannelAdapterRegistry — owns and manages all active channel adapters."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nodus_adapter_base import BaseChannelAdapter

logger = logging.getLogger(__name__)


class ChannelNotRegistered(LookupError):
    """A send was routed to a channel_id no adapter is registered for."""


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

    async def send(self, channel_id: str, content: str, peer_id: str, **kwargs) -> str:
        """Deliver one message; return the PROVIDER's id for it (Telegram's message_id, ...).

        Two reasons this is not `-> None` any more. The provider's id is the only identifier of
        a delivered message that does not come from us — it is what a mediated effect records as
        its receipt, and what lets the far side be counted independently. And an unknown
        channel_id used to log a warning and RETURN, which every caller read as success: with the
        AINDY effect seam on, that wrote a `success` ledger row for a message that was never sent.
        A send to a channel that is not registered is a failure and now says so.
        """
        adapter = self._adapters.get(channel_id)
        if adapter is None:
            raise ChannelNotRegistered(
                f"no adapter registered for channel {channel_id!r} "
                f"(registered: {sorted(self._adapters) or 'none'})"
            )
        return str(await adapter.send(content, peer_id, **kwargs) or "")
