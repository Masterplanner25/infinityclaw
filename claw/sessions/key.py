"""SessionKeyBuilder — deterministic session key from agent + scope."""
from __future__ import annotations

from claw.config.schema import SessionConfig


class SessionKeyBuilder:
    """Builds session keys following the configured dm_scope."""

    def __init__(self, config: SessionConfig) -> None:
        self._scope = config.dm_scope
        self._identity_links = config.identity_links

    def build(
        self,
        agent_id: str,
        channel_id: str,
        peer_id: str,
        *,
        account_id: str = "",
        thread_id: str = "",
    ) -> str:
        """Return a session key string for the given context.

        Scope semantics:
        - main              → agent:<agent_id>:main
        - per-peer          → agent:<agent_id>:peer:<canonical_peer>
        - per-channel-peer  → agent:<agent_id>:ch:<channel_id>:peer:<canonical_peer>
        - per-account-channel-peer → agent:<agent_id>:acct:<account_id>:ch:<channel_id>:peer:<canonical_peer>
        """
        canonical_peer = self._resolve_peer(peer_id)

        if self._scope == "main":
            return f"agent:{agent_id}:main"

        if self._scope == "per-peer":
            return f"agent:{agent_id}:peer:{canonical_peer}"

        if self._scope == "per-channel-peer":
            return f"agent:{agent_id}:ch:{channel_id}:peer:{canonical_peer}"

        if self._scope == "per-account-channel-peer":
            acct = account_id or channel_id
            return f"agent:{agent_id}:acct:{acct}:ch:{channel_id}:peer:{canonical_peer}"

        # Thread scope (explicit override)
        if thread_id:
            return f"agent:{agent_id}:thread:{thread_id}"

        return f"agent:{agent_id}:ch:{channel_id}:peer:{canonical_peer}"

    def _resolve_peer(self, peer_id: str) -> str:
        """Return the canonical peer id, following identity links."""
        for canonical, aliases in self._identity_links.items():
            if peer_id == canonical or peer_id in aliases:
                return canonical
        return peer_id
