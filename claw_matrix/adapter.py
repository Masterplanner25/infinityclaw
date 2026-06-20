"""MatrixAdapter — matrix-nio async client for Claw."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import Attachment, ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "matrix"


class MatrixAdapter(BaseChannelAdapter):
    """Matrix channel adapter using matrix-nio (async).

    Supports:
    - DM rooms (m.direct)
    - Public/private rooms (mention-gated)
    - Reply threading via m.relates_to

    Config:
        MATRIX_HOMESERVER — e.g. https://matrix.org
        MATRIX_USER_ID    — @bot:matrix.org
        MATRIX_PASSWORD   — password (or use access token)
        MATRIX_ACCESS_TOKEN — alternative to password
        MATRIX_REQUIRE_MENTION — bool (default: True in rooms)
        MATRIX_STORE_PATH — path for sync store (default: ~/.claw/matrix_store)
    """

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        *,
        password: str = "",
        access_token: str = "",
        require_mention: bool = True,
        store_path: str = "",
    ) -> None:
        super().__init__()
        self._homeserver = homeserver
        self._user_id = user_id
        self._password = password
        self._access_token = access_token
        self._require_mention = require_mention
        self._store_path = store_path or ""
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._client = None
        self._sync_task: Optional[asyncio.Task] = None
        self._dm_rooms: set[str] = set()

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="Matrix",
            supports_threads=True,
            supports_markdown=True,
            max_message_length=32000,
            supports_attachments=True,
        )

    async def _do_connect(self) -> None:
        import nio

        client_config = nio.AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=False,  # E2EE in Phase 5 via matrix-nio[e2e]
        )

        self._client = nio.AsyncClient(
            self._homeserver,
            self._user_id,
            config=client_config,
        )

        if self._access_token:
            self._client.access_token = self._access_token
            self._client.user_id = self._user_id
        elif self._password:
            resp = await self._client.login(self._password)
            if hasattr(resp, "access_token"):
                logger.info("[matrix] logged in as %s", self._user_id)
            else:
                raise RuntimeError(f"Matrix login failed: {resp}")
        else:
            raise RuntimeError("Matrix adapter requires password or access_token")

        # Register message callback
        self._client.add_event_callback(self._on_room_message, nio.RoomMessageText)

        # Fetch DM rooms to know which are DMs
        await self._refresh_dm_rooms()

        # Start sync loop
        self._sync_task = asyncio.create_task(
            self._client.sync_forever(30000, full_state=True),
            name="matrix:sync",
        )
        logger.info("[matrix] sync started for %s", self._user_id)

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
            raise RuntimeError("Matrix client not connected")

        room_id = peer_id
        content_dict = {
            "msgtype": "m.text",
            "body": content,
        }

        if reply_to_id:
            content_dict["m.relates_to"] = {
                "m.in_reply_to": {"event_id": reply_to_id}
            }

        await self._client.room_send(room_id, "m.room.message", content_dict)

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._inbound.get()
            yield msg

    async def _do_health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.whoami()
            return hasattr(resp, "user_id")
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._client:
            await self._client.close()
        self._connected = False
        logger.info("[matrix] disconnected")

    async def _refresh_dm_rooms(self) -> None:
        """Cache the list of DM room IDs."""
        if self._client is None:
            return
        try:
            account_data = await self._client.get_account_data("m.direct")
            if hasattr(account_data, "content"):
                for user_rooms in account_data.content.values():
                    self._dm_rooms.update(user_rooms)
        except Exception:
            pass

    async def _on_room_message(self, room, event) -> None:
        """matrix-nio event callback for m.room.message text events."""
        # Ignore own messages
        if event.sender == self._user_id:
            return

        text: str = event.body or ""
        room_id: str = room.room_id
        is_dm = room_id in self._dm_rooms

        # Mention gating for non-DM rooms
        if not is_dm and self._require_mention:
            local_part = self._user_id.split(":")[0].lstrip("@")
            if self._user_id not in text and local_part not in text:
                return

        # Strip mention from text
        text = text.replace(self._user_id, "").strip()

        if not text:
            return

        peer = Peer(
            id=room_id,
            channel_id=CHANNEL_ID,
            display_name=event.sender,
            raw=event,
        )

        reply_to = ""
        relates = getattr(event, "relates_to", None)
        if relates and hasattr(relates, "in_reply_to"):
            reply_to = relates.in_reply_to.event_id or ""

        msg = Message(
            id=event.event_id,
            channel_id=CHANNEL_ID,
            sender=peer,
            content=text,
            timestamp=None,
            attachments=[],
            reply_to_id=reply_to,
            thread_id="",
            raw=event,
        )
        await self._inbound.put(msg)
