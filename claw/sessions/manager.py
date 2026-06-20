"""ClawSessionManager — wraps nodus_session with per-session asyncio locks."""
from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Optional

from nodus_session import (
    InMemorySessionStore,
    SessionEntry,
    SessionManager,
    SessionPruningPolicy,
)

from claw.config.schema import SessionConfig
from .compactor import ContextCompactor
from .pruner import ContextPruner

logger = logging.getLogger(__name__)


class ClawSessionManager:
    """Session management with per-key asyncio locks for turn serialization.

    nodus_session.SessionManager handles storage; we add:
    - Per-session asyncio.Lock so concurrent inbound messages for the same
      session are processed in FIFO order (not via nodus_queue which is a
      distributed job queue, not a per-session serializer).
    - Daily reset logic aligned with SessionConfig.reset.
    - Context pruning via ContextPruner.
    """

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._store = InMemorySessionStore()
        policy = SessionPruningPolicy(max_messages=config.max_messages)
        self._manager = SessionManager(store=self._store, policy=policy)
        self._locks: dict[str, asyncio.Lock] = {}
        self._pruner = ContextPruner(max_messages=config.max_messages)
        self._compactor = ContextCompactor(
            threshold=config.compaction_threshold,
            keep_recent=config.compaction_keep_recent,
        )

    def lock_for(self, session_key: str) -> asyncio.Lock:
        """Return (or create) the asyncio.Lock for *session_key*."""
        if session_key not in self._locks:
            self._locks[session_key] = asyncio.Lock()
        return self._locks[session_key]

    def get_or_create(self, session_key: str, provenance: Optional[dict] = None) -> SessionEntry:
        return self._manager.get_or_create(session_key, provenance=provenance or {})

    def get_messages(self, session_key: str) -> list[dict]:
        """Return Anthropic-format message list for *session_key*.

        Strips any extra fields added by nodus_session (e.g. timestamp)
        since the Anthropic API only accepts role + content.
        """
        entry = self._manager.get_or_create(session_key)
        clean = []
        for m in entry.messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            content = m.get("content")
            if role and content is not None:
                clean.append({"role": role, "content": content})
        return clean

    def append_user_message(self, session_key: str, content: str) -> None:
        msg = {"role": "user", "content": content}
        self._manager.append_message(session_key, msg)

    def append_assistant_message(self, session_key: str, content: str) -> None:
        msg = {"role": "assistant", "content": content}
        self._manager.append_message(session_key, msg)

    def prune_if_needed(self, session_key: str) -> None:
        entry = self._manager.get_or_create(session_key)
        if len(entry.messages) > self._config.max_messages:
            self._manager.prune(agent_id=session_key)
            logger.debug("[session] pruned %s to %d messages", session_key, self._config.max_messages)

    async def compact_if_needed(self, session_key: str, turn) -> list[dict]:
        """Compact messages if they exceed the compaction threshold.

        Returns the (possibly compacted) message list and writes it back to the session.
        """
        messages = self.get_messages(session_key)
        if not self._compactor.needs_compaction(messages):
            return messages
        compacted = await self._compactor.compact(messages, turn)
        # Write compacted list back: clear + re-append
        entry = self._manager.get_or_create(session_key)
        entry.messages.clear()
        for msg in compacted:
            self._manager.append_message(session_key, msg)
        return compacted

    def reset(self, session_key: str) -> None:
        """Clear the session's message history (daily reset)."""
        entry = self._manager.get_or_create(session_key)
        entry.messages.clear()
        entry.touch()
        logger.info("[session] reset %s", session_key)

    def all_keys(self) -> list[str]:
        return list(self._locks.keys())
