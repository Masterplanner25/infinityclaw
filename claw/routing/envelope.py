"""Inbound and outbound message envelopes for routing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class InboundEnvelope:
    """Normalized inbound message from any channel adapter."""
    channel_id: str
    peer_id: str
    content: str
    message_id: str = ""
    thread_id: str = ""
    reply_to_id: str = ""
    account_id: str = ""
    guild_id: str = ""
    team_id: str = ""
    roles: list[str] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)
    agent_id: str = ""   # explicit agent override; respected before binding resolution
    raw: Any = None


@dataclass
class OutboundEnvelope:
    """Normalized outbound message to a channel adapter."""
    channel_id: str
    peer_id: str
    content: str
    thread_id: str = ""
    reply_to_id: str = ""
    attachments: list[Any] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
