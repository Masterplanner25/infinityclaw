"""Delegation tool — lets an agent hand off a task to another agent."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.tools.registry import ToolRegistry
    from claw.coordination.dispatcher import AgentDispatcher

_DELEGATION_TOOL = "delegate_to_agent"


def is_coordination_tool(name: str) -> bool:
    """Return True if name is a coordination tool that needs _agent_id injected."""
    return name == _DELEGATION_TOOL


def register_delegation_tool(
    registry: "ToolRegistry",
    dispatcher: "AgentDispatcher",
) -> None:
    """Register the delegate_to_agent tool on the shared ToolRegistry."""

    async def _handle(inp: dict) -> str:
        from claw.coordination.model import HandoffRequest
        req = HandoffRequest(
            from_agent=inp.get("_agent_id", "unknown"),
            to_agent=inp["agent_id"],
            prompt=inp["prompt"],
            context=inp.get("context", ""),
        )
        result = await dispatcher.dispatch(req)
        if result.success:
            return result.response
        return json.dumps({"error": result.error})

    registry.register(
        name=_DELEGATION_TOOL,
        description=(
            "Delegate a task or question to another agent. "
            "The target agent processes the prompt independently and returns its response."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to delegate to.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The task or question for the target agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context for the target agent.",
                },
            },
            "required": ["agent_id", "prompt"],
        },
        handler=_handle,
    )
