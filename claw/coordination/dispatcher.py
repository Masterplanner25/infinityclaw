"""AgentDispatcher — runs a stateless inner turn on behalf of another agent."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .model import HandoffRequest, HandoffResult

if TYPE_CHECKING:
    from claw.gateway.server import ClawGateway

logger = logging.getLogger(__name__)


class AgentDispatcher:
    """Dispatches a task from one agent to another via an inner turn.

    The target agent processes the prompt without session history — each
    delegation is stateless. Session continuity for delegated flows is
    Phase 9+.
    """

    def __init__(self, gateway: "ClawGateway") -> None:
        self._gw = gateway

    async def dispatch(self, req: HandoffRequest) -> HandoffResult:
        """Run an inner turn for req.to_agent and return the result."""
        known = {a.id for a in self._gw.config.agents.agents}
        if req.to_agent not in known:
            return HandoffResult(
                from_agent=req.from_agent,
                to_agent=req.to_agent,
                prompt=req.prompt,
                response="",
                success=False,
                error=f"Unknown agent '{req.to_agent}'",
            )

        response = await self._gw.run_agent_turn(
            agent_id=req.to_agent,
            prompt=req.prompt,
            context=req.context,
        )
        success = not response.startswith("[error:")
        return HandoffResult(
            from_agent=req.from_agent,
            to_agent=req.to_agent,
            prompt=req.prompt,
            response=response,
            success=success,
            error=response if not success else "",
        )
