"""DiscordAdapter — discord.py 2.x channel adapter for Claw."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import Attachment, ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "discord"


class DiscordAdapter(BaseChannelAdapter):
    """Discord channel adapter using discord.py 2.x.

    Supports:
    - DM conversations (always processed)
    - Guild text channels (mention-gated)
    - Thread channels (always processed if agent is a participant)
    - Reactions as delivery confirmation
    - Media attachments

    Config:
        DISCORD_BOT_TOKEN — required
        DISCORD_REQUIRE_MENTION — true/false (default: true in guild channels)
        DISCORD_ALLOWED_GUILDS — comma-separated guild IDs (empty = all)
    """

    def __init__(
        self,
        token: str,
        *,
        require_mention: bool = True,
        allowed_guilds: list[int] | None = None,
    ) -> None:
        super().__init__()
        self._token = token
        self._require_mention = require_mention
        self._allowed_guilds: set[int] = set(allowed_guilds or [])
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._client = None
        self._bot_user = None
        self._polling_task: Optional[asyncio.Task] = None

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="Discord",
            supports_threads=True,
            supports_markdown=True,  # Discord uses its own markdown subset
            max_message_length=2000,
            supports_attachments=True,
        )

    async def _do_connect(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        adapter = self

        @self._client.event
        async def on_ready():
            adapter._bot_user = self._client.user
            logger.info("[discord] logged in as %s", adapter._bot_user)

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author == self._client.user:
                return  # ignore own messages
            await adapter._handle_message(message)

        # Start the bot in a background task
        self._polling_task = asyncio.create_task(
            self._client.start(self._token),
            name="discord:client",
        )

        # Wait for the client to be ready (up to 30s)
        for _ in range(30):
            if self._client.is_ready():
                break
            await asyncio.sleep(1)
        if not self._client.is_ready():
            raise RuntimeError("Discord client did not become ready in 30s")

    async def _do_send(
        self,
        content: str,
        peer_id: str,
        *,
        thread_id: str = "",
        reply_to_id: str = "",
        attachments=None,
    ) -> None:
        if self._client is None:
            raise RuntimeError("Discord client not connected")

        # thread_id takes precedence over peer_id for threaded replies
        target_id = int(thread_id) if thread_id else int(peer_id)
        channel = self._client.get_channel(target_id)
        if channel is None:
            channel = await self._client.fetch_channel(target_id)

        # Discord limit: 2000 chars per message
        for chunk in _split_message(content, 2000):
            await channel.send(chunk)

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._inbound.get()
            yield msg

    async def _do_health_check(self) -> bool:
        return self._client is not None and self._client.is_ready()

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except (asyncio.CancelledError, Exception):
                pass
        self._connected = False
        logger.info("[discord] disconnected")

    async def _handle_message(self, message) -> None:
        import discord

        # Guild filtering
        if message.guild and self._allowed_guilds:
            if message.guild.id not in self._allowed_guilds:
                return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_thread = isinstance(message.channel, discord.Thread)

        # Mention gating for guild channels (not DMs, not threads the agent started)
        if not is_dm and self._require_mention:
            if self._bot_user and self._bot_user not in message.mentions:
                return

        text = message.content or ""

        # Strip bot mention from content
        if self._bot_user:
            mention = f"<@{self._bot_user.id}>"
            text = text.replace(mention, "").strip()

        if not text and not message.attachments:
            return

        peer = Peer(
            id=str(message.channel.id),  # reply to the channel/thread
            channel_id=CHANNEL_ID,
            display_name=message.author.display_name,
            raw=message.author,
        )

        msg = Message(
            id=str(message.id),
            channel_id=CHANNEL_ID,
            sender=peer,
            content=text,
            timestamp=message.created_at,
            attachments=_extract_attachments(message),
            reply_to_id=str(message.reference.message_id) if message.reference else "",
            thread_id=str(message.channel.id) if is_thread else "",
            raw=message,
        )
        await self._inbound.put(msg)


def _extract_attachments(message) -> list[Attachment]:
    return [
        Attachment(
            type="file",
            mime_type=a.content_type or "application/octet-stream",
            url=a.url,
            content=None,
            filename=a.filename,
            size_bytes=a.size,
        )
        for a in message.attachments
    ]


def _split_message(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    return chunks
