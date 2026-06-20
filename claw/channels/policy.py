"""DmPolicyEnforcer — controls who can send messages to an agent."""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class DmPolicy(str, Enum):
    OPEN = "open"           # anyone can message
    ALLOWLIST = "allowlist" # only listed peer_ids
    PAIRING = "pairing"     # must complete pairing handshake first


class DmPolicyEnforcer:
    """Decides whether an inbound message should be processed.

    Policy per channel_id (or global default):
    - open:      all messages accepted
    - allowlist: only peer_ids in allowed_peers pass
    - pairing:   peer must appear in paired_peers (set by PairingStore)
    """

    def __init__(
        self,
        default_policy: DmPolicy = DmPolicy.OPEN,
        allowed_peers: dict[str, set[str]] | None = None,
        paired_peers: dict[str, set[str]] | None = None,
        channel_policies: dict[str, DmPolicy] | None = None,
    ) -> None:
        self._default = default_policy
        self._allowed: dict[str, set[str]] = allowed_peers or {}
        self._paired: dict[str, set[str]] = paired_peers or {}
        self._channel_policies: dict[str, DmPolicy] = channel_policies or {}

    def allow(self, channel_id: str, peer_id: str) -> bool:
        policy = self._channel_policies.get(channel_id, self._default)

        if policy == DmPolicy.OPEN:
            return True

        if policy == DmPolicy.ALLOWLIST:
            allowed = self._allowed.get(channel_id, set())
            result = peer_id in allowed
            if not result:
                logger.debug("[policy] ALLOWLIST denied channel=%s peer=%s", channel_id, peer_id)
            return result

        if policy == DmPolicy.PAIRING:
            paired = self._paired.get(channel_id, set())
            result = peer_id in paired
            if not result:
                logger.debug("[policy] PAIRING denied channel=%s peer=%s", channel_id, peer_id)
            return result

        return False

    def add_paired_peer(self, channel_id: str, peer_id: str) -> None:
        self._paired.setdefault(channel_id, set()).add(peer_id)

    def add_allowed_peer(self, channel_id: str, peer_id: str) -> None:
        self._allowed.setdefault(channel_id, set()).add(peer_id)
