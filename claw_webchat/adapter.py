"""WebChatAdapter — FastAPI WebSocket channel for browser-based chat."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncIterator, Optional

from fastapi import WebSocket
from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "webchat"


class WebChatAdapter(BaseChannelAdapter):
    """Single-session WebSocket channel for the built-in WebChat UI.

    Each browser connection gets a unique peer_id. Messages flow through
    the standard channel adapter interface so the gateway can route them.
    """

    def __init__(self) -> None:
        super().__init__()
        self._outbox: asyncio.Queue[Message] = asyncio.Queue()
        self._active_ws: dict[str, WebSocket] = {}  # peer_id → websocket

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="WebChat",
            supports_threads=False,
            supports_markdown=True,
            max_message_length=10_000,
            supports_attachments=False,
        )

    async def _do_connect(self) -> None:
        self._connected = True
        logger.info("[webchat] adapter ready")

    async def _do_send(
        self,
        content: str,
        peer_id: str,
        *,
        thread_id: str = "",
        reply_to_id: str = "",
        attachments=None,
    ) -> None:
        ws = self._active_ws.get(peer_id)
        if ws is None:
            logger.warning("[webchat] no active WS for peer=%s", peer_id)
            return
        import json
        await ws.send_text(json.dumps({"type": "message", "content": content}))

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._outbox.get()
            yield msg

    async def handle_ws_connection(
        self,
        websocket: WebSocket,
        *,
        on_message,
        peer_id: Optional[str] = None,
    ) -> None:
        """Handle one WebSocket connection from the gateway.

        Args:
            websocket:  The FastAPI WebSocket instance.
            on_message: Async callable(InboundEnvelope) → None.
            peer_id:    Stable peer id (auto-generated if not provided).
        """
        import json
        from claw.routing.envelope import InboundEnvelope

        peer_id = peer_id or str(uuid.uuid4())
        self._active_ws[peer_id] = websocket

        try:
            await websocket.send_text(json.dumps({
                "type": "hello",
                "peer_id": peer_id,
                "channel": CHANNEL_ID,
            }))

            async for raw in websocket.iter_text():
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "message": "invalid JSON"}))
                    continue

                frame_type = frame.get("type")

                if frame_type == "chat":
                    content = frame.get("content", "").strip()
                    if not content:
                        continue
                    envelope = InboundEnvelope(
                        channel_id=CHANNEL_ID,
                        peer_id=peer_id,
                        content=content,
                        message_id=str(uuid.uuid4()),
                        agent_id=frame.get("agent_id", ""),
                    )
                    try:
                        await on_message(envelope)
                    except Exception as exc:
                        logger.error("[webchat] on_message error: %s", exc)
                        await self.send_error(peer_id, f"Internal error: {exc}")

                elif frame_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

        except Exception as exc:
            logger.debug("[webchat] connection closed peer=%s: %s", peer_id, exc)
        finally:
            self._active_ws.pop(peer_id, None)

    async def stream_chunk(self, peer_id: str, chunk: str) -> None:
        """Send a streaming text chunk to a connected WebChat peer."""
        ws = self._active_ws.get(peer_id)
        if ws:
            import json
            try:
                await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))
            except Exception:
                pass

    async def send_done(self, peer_id: str) -> None:
        """Signal end of a streaming response."""
        ws = self._active_ws.get(peer_id)
        if ws:
            import json
            try:
                await ws.send_text(json.dumps({"type": "done"}))
            except Exception:
                pass

    async def send_error(self, peer_id: str, message: str) -> None:
        ws = self._active_ws.get(peer_id)
        if ws:
            import json
            try:
                await ws.send_text(json.dumps({"type": "error", "message": message}))
            except Exception:
                pass
