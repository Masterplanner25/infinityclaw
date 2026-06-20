"""IdentityLinker — resolves peer aliases and cross-channel identities."""
from __future__ import annotations

from claw.config.schema import SessionConfig


class IdentityLinker:
    """Maps peer IDs to canonical identities using configured identity_links."""

    def __init__(self, config: SessionConfig) -> None:
        # Build reverse lookup: alias → canonical
        self._reverse: dict[str, str] = {}
        for canonical, aliases in config.identity_links.items():
            self._reverse[canonical] = canonical
            for alias in aliases:
                self._reverse[alias] = canonical

    def canonical(self, peer_id: str) -> str:
        """Return the canonical peer id for *peer_id*."""
        return self._reverse.get(peer_id, peer_id)

    def aliases_for(self, peer_id: str) -> list[str]:
        """Return all known aliases for the canonical peer of *peer_id*."""
        canonical = self.canonical(peer_id)
        return [k for k, v in self._reverse.items() if v == canonical]
