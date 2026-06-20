"""SlackAdapter — slack-bolt based channel adapter for Claw."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import Attachment, ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "slack"


class SlackAdapter(BaseChannelAdapter):
    """Slack channel adapter using slack-bolt async.

    Supports:
    - DM conversations
    - Public/private channels (mention-gated)
    - Thread replies (in-thread conversation isolation)
    - App mentions

    Config:
        SLACK_BOT_TOKEN   — required (xoxb-...)
        SLACK_APP_TOKEN   — required for Socket Mode (xapp-...)
        SLACK_REQUIRE_MENTION — bool (default: True in channels)
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        *,
        require_mention: bool = True,
    ) -> None:
        super().__init__()
        self._bot_token = bot_token
        self._app_token = app_token
        self._require_mention = require_mention
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._app = None
        self._handler = None
        self._bot_user_id: Optional[str] = None
        self._socket_task: Optional[asyncio.Task] = None

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="Slack",
            supports_threads=True,
            supports_markdown=True,
            max_message_length=3000,
            supports_attachments=True,
        )

    async def _do_connect(self) -> None:
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

        self._app = AsyncApp(token=self._bot_token)
        adapter = self

        # Register event listeners
        @self._app.event("message")
        async def handle_message(event, say, client):
            await adapter._handle_message_event(event, client)

        @self._app.event("app_mention")
        async def handle_mention(event, say, client):
            await adapter._handle_message_event(event, client)

        # Fetch bot user ID for mention detection
        try:
            result = await self._app.client.auth_test()
            self._bot_user_id = result["user_id"]
        except Exception as exc:
            logger.warning("[slack] could not fetch bot user ID: %s", exc)

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        self._socket_task = asyncio.create_task(
            self._handler.start_async(),
            name="slack:socket",
        )
        logger.info("[slack] connected via Socket Mode (bot_user=%s)", self._bot_user_id)

    async def _do_send(
        self,
        content: str,
        peer_id: str,
        *,
        thread_id: str = "",
        reply_to_id: str = "",
        attachments=None,
    ) -> None:
        if self._app is None:
            raise RuntimeError("Slack app not connected")

        kwargs = {"channel": peer_id, "text": content}
        if thread_id:
            kwargs["thread_ts"] = thread_id

        await self._app.client.chat_postMessage(**kwargs)

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._inbound.get()
            yield msg

    async def _do_health_check(self) -> bool:
        if self._app is None:
            return False
        try:
            result = await self._app.client.auth_test()
            return result.get("ok", False)
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._handler:
            try:
                await self._handler.close_async()
            except Exception:
                pass
        if self._socket_task:
            self._socket_task.cancel()
            try:
                await self._socket_task
            except (asyncio.CancelledError, Exception):
                pass
        self._connected = False
        logger.info("[slack] disconnected")

    async def _handle_message_event(self, event: dict, client) -> None:
        # Ignore bot messages and edits
        if event.get("bot_id") or event.get("subtype"):
            return

        text: str = event.get("text", "")
        channel = event.get("channel", "")
        user = event.get("user", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts", "")
        channel_type = event.get("channel_type", "")

        is_dm = channel_type == "im"

        # Mention gating for non-DM channels
        if not is_dm and self._require_mention:
            if self._bot_user_id and f"<@{self._bot_user_id}>" not in text:
                return

        # Strip bot mention from text
        if self._bot_user_id:
            text = text.replace(f"<@{self._bot_user_id}>", "").strip()

        if not text:
            return

        # Fetch user display name
        display_name = user
        try:
            user_info = await client.users_info(user=user)
            display_name = (
                user_info["user"].get("real_name")
                or user_info["user"]["profile"].get("display_name")
                or user
            )
        except Exception:
            pass

        peer = Peer(
            id=channel,
            channel_id=CHANNEL_ID,
            display_name=display_name,
            raw=event,
        )

        msg = Message(
            id=ts,
            channel_id=CHANNEL_ID,
            sender=peer,
            content=text,
            timestamp=None,
            attachments=[],
            reply_to_id="",
            thread_id=thread_ts or "",
            raw=event,
        )
        await self._inbound.put(msg)
