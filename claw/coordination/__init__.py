"""Agent coordination — delegation, handoff, and cross-agent task routing."""
from .model import HandoffRequest, HandoffResult
from .dispatcher import AgentDispatcher
from .tools import register_delegation_tool, is_coordination_tool

__all__ = [
    "HandoffRequest",
    "HandoffResult",
    "AgentDispatcher",
    "register_delegation_tool",
    "is_coordination_tool",
]
