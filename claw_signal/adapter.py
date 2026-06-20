"""SignalAdapter — signal-cli JSON-RPC bridge for Claw."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import AsyncIterator, Optional

from nodus_adapter_base import BaseChannelAdapter
from nodus_channels import Attachment, ChannelInfo, Message, Peer

logger = logging.getLogger(__name__)

CHANNEL_ID = "signal"


class SignalAdapter(BaseChannelAdapter):
    """Signal channel adapter via signal-cli subprocess JSON-RPC bridge.

    Requires signal-cli to be installed and registered:
        https://github.com/AsamK/signal-cli

    signal-cli must be pre-registered with a phone number.
    This adapter spawns signal-cli in --json-rpc mode and communicates
    over stdin/stdout.

    Config:
        SIGNAL_PHONE_NUMBER — registered number (e.g. +14155552671)
        SIGNAL_CLI_PATH — path to signal-cli binary (default: signal-cli on PATH)
        SIGNAL_DATA_PATH — signal-cli data directory (default: ~/.local/share/signal-cli)
    """

    def __init__(
        self,
        phone_number: str,
        *,
        cli_path: str = "signal-cli",
        data_path: str = "",
    ) -> None:
        super().__init__()
        self._phone = phone_number
        self._cli_path = cli_path
        self._data_path = data_path
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._inbound: asyncio.Queue[Message] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._request_id = 0

    @property
    def channel_id(self) -> str:
        return CHANNEL_ID

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=CHANNEL_ID,
            display_name="Signal",
            supports_threads=False,
            supports_markdown=False,
            max_message_length=2000,
            supports_attachments=True,
        )

    async def _do_connect(self) -> None:
        cmd = [self._cli_path, "-u", self._phone, "jsonRpc"]
        if self._data_path:
            cmd = [self._cli_path, "--config", self._data_path, "-u", self._phone, "jsonRpc"]

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(
            self._read_loop(),
            name="signal:reader",
        )
        logger.info("[signal] connected phone=%s", self._phone)

    async def _do_send(
        self,
        content: str,
        peer_id: str,
        *,
        thread_id: str = "",
        reply_to_id: str = "",
        attachments=None,
    ) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Signal process not running")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "send",
            "id": self._request_id,
            "params": {
                "recipient": [peer_id],
                "message": content,
            },
        }
        if reply_to_id:
            payload["params"]["quote-timestamp"] = int(reply_to_id)

        line = json.dumps(payload) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _do_subscribe(self) -> AsyncIterator[Message]:
        while True:
            msg = await self._inbound.get()
            yield msg

    async def _do_health_check(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                pass
        self._connected = False
        logger.info("[signal] disconnected")

    async def _read_loop(self) -> None:
        """Read JSON-RPC lines from signal-cli stdout and dispatch messages."""
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            async for raw_line in self._proc.stdout:
                line = raw_line.decode().strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    await self._dispatch(data)
                except json.JSONDecodeError:
                    logger.warning("[signal] bad JSON from signal-cli: %s", line[:100])
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[signal] reader error: %s", exc)

    async def _dispatch(self, data: dict) -> None:
        """Parse a signal-cli JSON-RPC event and enqueue as Message."""
        method = data.get("method")
        if method != "receive":
            return

        params = data.get("params", {})
        envelope = params.get("envelope", {})
        data_msg = envelope.get("dataMessage", {})

        text = data_msg.get("message", "")
        if not text:
            return

        sender = envelope.get("sourceNumber") or envelope.get("sourceUuid") or "unknown"
        timestamp = envelope.get("timestamp", 0)

        peer = Peer(
            id=sender,
            channel_id=CHANNEL_ID,
            display_name=sender,
            raw=envelope,
        )

        msg = Message(
            id=str(timestamp),
            channel_id=CHANNEL_ID,
            sender=peer,
            content=text,
            timestamp=None,
            attachments=[],
            reply_to_id="",
            thread_id="",
            raw=data,
        )
        await self._inbound.put(msg)
