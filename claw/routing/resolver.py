"""BindingResolver — 8-tier most-specific-wins routing."""
from __future__ import annotations

import logging
from typing import Optional

from claw.config.schema import Binding, BindingMatch
from .envelope import InboundEnvelope

logger = logging.getLogger(__name__)

# Tier weight: higher = more specific (wins)
_TIER_WEIGHT = {
    "peer": 70,
    "peer_channel": 60,
    "guild_roles": 50,
    "guild": 40,
    "team": 30,
    "account": 20,
    "channel": 10,
    "default": 0,
}


class BindingResolver:
    """Resolves which agent should handle an inbound message.

    Implements 8-tier specificity matching (most-specific-wins).
    Falls back to the first configured agent if no binding matches.
    """

    def __init__(self, bindings: list[Binding], fallback_agent_id: str = "main") -> None:
        self._bindings = bindings
        self._fallback = fallback_agent_id

    def resolve(self, envelope: InboundEnvelope) -> str:
        """Return the agent_id that should handle *envelope*."""
        if envelope.agent_id:
            logger.debug("[router] explicit agent=%s", envelope.agent_id)
            return envelope.agent_id

        best_agent: Optional[str] = None
        best_weight = -1

        for binding in self._bindings:
            weight = self._score(binding.match, envelope)
            if weight >= 0 and weight > best_weight:
                best_weight = weight
                best_agent = binding.agent_id

        result = best_agent or self._fallback
        logger.debug("[router] %s/%s → agent=%s (weight=%d)", envelope.channel_id, envelope.peer_id, result, best_weight)
        return result

    def _score(self, match: BindingMatch, env: InboundEnvelope) -> int:
        """Return specificity weight (≥0 if matches, -1 if no match)."""
        # Specific peer on specific channel (tier 7)
        if match.peer_id and match.channel_id:
            if env.peer_id == match.peer_id and env.channel_id == match.channel_id:
                return _TIER_WEIGHT["peer_channel"]
            return -1

        # Any channel for specific peer (tier 6)
        if match.peer_id:
            if env.peer_id == match.peer_id:
                return _TIER_WEIGHT["peer"]
            return -1

        # Guild + roles (tier 5)
        if match.guild_id and match.roles:
            if env.guild_id == match.guild_id and any(r in env.roles for r in match.roles):
                return _TIER_WEIGHT["guild_roles"]
            return -1

        # Guild (tier 4)
        if match.guild_id:
            if env.guild_id == match.guild_id:
                return _TIER_WEIGHT["guild"]
            return -1

        # Team (tier 3)
        if match.team_id:
            if env.team_id == match.team_id:
                return _TIER_WEIGHT["team"]
            return -1

        # Account (tier 2)
        if match.account_id:
            if env.account_id == match.account_id:
                return _TIER_WEIGHT["account"]
            return -1

        # Channel type (tier 1)
        if match.channel or match.channel_id:
            pattern = match.channel_id or match.channel
            if env.channel_id == pattern or env.channel_id.startswith(f"{pattern}:"):
                return _TIER_WEIGHT["channel"]
            return -1

        # Default catch-all (tier 0)
        return _TIER_WEIGHT["default"]
