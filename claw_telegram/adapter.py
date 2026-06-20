"""TelegramAdapter — aiogram 3.x channel adapter for Claw."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import Attachment, ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "telegram"


class TelegramAdapter(BaseChannelAdapter):
    """Telegram channel adapter using aiogram 3.x.

    Supports:
    - DM conversations
    - Group/supergroup messages (mention-gated via require_mention)
    - Topic threads in supergroups
    - Typing indicators
    - Media normalization (photo, document, voice, video)

    Config keys (all from env or claw.toml):
        TELEGRAM_BOT_TOKEN  — required
        TELEGRAM_REQUIRE_MENTION — true/false (default: true in groups)
        TELEGRAM_ALLOWED_USERS — comma-separated user IDs (empty = all)
    """

    def __init__(
        self,
        token: str,
        *,
        require_mention: bool = True,
        allowed_users: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._token = token
        self._require_mention = require_mention
        self._allowed_users: set[str] = set(allowed_users or [])
        self._bot = None
        self._dispatcher = None
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._polling_task: Optional[asyncio.Task] = None

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="Telegram",
            supports_threads=True,
            supports_markdown=True,
            max_message_length=4096,
            supports_attachments=True,
        )

    async def _do_connect(self) -> None:
        from aiogram import Bot, Dispatcher
        from aiogram.enums import ParseMode

        self._bot = Bot(token=self._token, parse_mode=ParseMode.MARKDOWN_V2)
        self._dispatcher = Dispatcher()
        self._register_handlers()

        # Start long-polling in the background
        self._polling_task = asyncio.create_task(
            self._dispatcher.start_polling(self._bot, handle_signals=False),
            name="telegram:polling",
        )
        logger.info("[telegram] connected (bot polling started)")

    async def _do_send(
        self,
        content: str,
        peer_id: str,
        *,
        thread_id: str = "",
        reply_to_id: str = "",
        attachments=None,
    ) -> None:
        if self._bot is None:
            raise RuntimeError("Telegram bot not connected")

        chat_id = int(peer_id)
        kwargs = {}
        if thread_id:
            kwargs["message_thread_id"] = int(thread_id)
        if reply_to_id:
            kwargs["reply_to_message_id"] = int(reply_to_id)

        # Escape markdown for Telegram MarkdownV2
        text = _escape_md(content)

        try:
            await self._bot.send_message(chat_id, text, **kwargs)
        except Exception as exc:
            # Fallback to plain text on markdown errors
            logger.warning("[telegram] markdown send failed, retrying plain: %s", exc)
            await self._bot.send_message(chat_id, content, parse_mode=None, **kwargs)

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._inbound.get()
            yield msg

    async def _do_health_check(self) -> bool:
        if self._bot is None:
            return False
        try:
            me = await self._bot.get_me()
            return me is not None
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        if self._bot:
            await self._bot.session.close()
        self._connected = False
        logger.info("[telegram] disconnected")

    def _register_handlers(self) -> None:
        from aiogram import F
        from aiogram.filters import Command
        from aiogram.types import Message as TgMessage

        dp = self._dispatcher

        @dp.message()
        async def on_message(tg_msg: TgMessage) -> None:
            await self._handle_message(tg_msg)

    async def _handle_message(self, tg_msg) -> None:
        from aiogram.types import Message as TgMessage

        # Filter by allowed users
        sender_id = str(tg_msg.from_user.id) if tg_msg.from_user else ""
        if self._allowed_users and sender_id not in self._allowed_users:
            return

        # Mention gating for groups
        is_private = tg_msg.chat.type == "private"
        if not is_private and self._require_mention:
            if not _has_bot_mention(tg_msg):
                return

        # Typing indicator
        try:
            await tg_msg.answer_chat_action("typing")
        except Exception:
            pass

        # Build normalized Message
        text = tg_msg.text or tg_msg.caption or ""
        if not text and not tg_msg.photo and not tg_msg.document and not tg_msg.voice:
            return

        attachments = _extract_attachments(tg_msg)
        peer = Peer(
            id=sender_id,
            channel_id=CHANNEL_ID,
            display_name=_display_name(tg_msg.from_user),
            raw=tg_msg.from_user,
        )

        msg = Message(
            id=str(tg_msg.message_id),
            channel_id=CHANNEL_ID,
            sender=peer,
            content=text,
            timestamp=tg_msg.date,
            attachments=attachments,
            reply_to_id=str(tg_msg.reply_to_message.message_id) if tg_msg.reply_to_message else "",
            thread_id=str(tg_msg.message_thread_id) if tg_msg.message_thread_id else "",
            raw=tg_msg,
        )

        # Override peer_id to chat_id for reply routing (reply to the chat, not the user)
        msg.sender.id = str(tg_msg.chat.id)

        await self._inbound.put(msg)


def _has_bot_mention(tg_msg) -> bool:
    entities = tg_msg.entities or []
    for entity in entities:
        if entity.type == "mention":
            return True
    return False


def _display_name(user) -> str:
    if user is None:
        return "unknown"
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or user.username or str(user.id)


def _extract_attachments(tg_msg) -> list[Attachment]:
    attachments = []
    if tg_msg.photo:
        # Largest photo size
        photo = tg_msg.photo[-1]
        attachments.append(Attachment(
            type="image",
            mime_type="image/jpeg",
            url="",
            content=None,
            filename=f"photo_{photo.file_id}.jpg",
            size_bytes=photo.file_size or 0,
        ))
    if tg_msg.document:
        doc = tg_msg.document
        attachments.append(Attachment(
            type="file",
            mime_type=doc.mime_type or "application/octet-stream",
            url="",
            content=None,
            filename=doc.file_name or doc.file_id,
            size_bytes=doc.file_size or 0,
        ))
    if tg_msg.voice:
        attachments.append(Attachment(
            type="audio",
            mime_type="audio/ogg",
            url="",
            content=None,
            filename=f"voice_{tg_msg.voice.file_id}.ogg",
            size_bytes=tg_msg.voice.file_size or 0,
        ))
    return attachments


_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"

def _escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    result = []
    for ch in text:
        if ch in _MD_SPECIAL:
            result.append("\\")
        result.append(ch)
    return "".join(result)
