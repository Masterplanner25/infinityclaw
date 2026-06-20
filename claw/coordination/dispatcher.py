"""AgentDispatcher — runs a stateless inner turn on behalf of another agent."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from .model import HandoffRequest, HandoffResult

if TYPE_CHECKING:
    from claw.gateway.server import ClawGateway

logger = logging.getLogger(__name__)


async def _emit_event(client, event_type: str, payload: dict) -> None:
    try:
        await client.emit_event(event_type, payload)
    except Exception:
        pass


class AgentDispatcher:
    """Dispatches a task from one agent to another via an inner turn.

    When HandoffRequest.session_key is set, the target agent runs with
    session-persistent history (Phase 10). When empty, the turn is
    stateless (Phase 8 behavior).

    Each dispatch emits AINDY audit events when AINDY is enabled (Phase 11):
    claw.delegation.started, claw.delegation.complete, claw.delegation.error.
    """

    def __init__(self, gateway: "ClawGateway") -> None:
        self._gw = gateway

    async def dispatch(self, req: HandoffRequest) -> HandoffResult:
        """Run an inner turn for req.to_agent and return the result."""
        _aindy = self._gw._aindy
        _emit = _aindy is not None and self._gw.config.aindy.emit_events
        delegation_id = str(uuid.uuid4())
        _base = {
            "from_agent": req.from_agent,
            "to_agent": req.to_agent,
            "delegation_id": delegation_id,
            "persistent": bool(req.session_key),
        }
        if req.session_key:
            _base["session_key"] = req.session_key

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

        if _emit:
            asyncio.create_task(_emit_event(_aindy, "claw.delegation.started", _base))

        response = await self._gw.run_agent_turn(
            agent_id=req.to_agent,
            prompt=req.prompt,
            context=req.context,
            session_key=req.session_key,
        )
        success = not response.startswith("[error:")

        if _emit:
            if success:
                asyncio.create_task(_emit_event(_aindy, "claw.delegation.complete", {
                    **_base,
                    "response_len": len(response),
                }))
            else:
                asyncio.create_task(_emit_event(_aindy, "claw.delegation.error", {
                    **_base,
                    "error": response[:200],
                }))

        return HandoffResult(
            from_agent=req.from_agent,
            to_agent=req.to_agent,
            prompt=req.prompt,
            response=response,
            success=success,
            error=response if not success else "",
        )
