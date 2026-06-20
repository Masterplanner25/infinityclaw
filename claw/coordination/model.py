"""Data models for agent-to-agent handoff and delegation."""
from __future__ import annotations

from pydantic import BaseModel


class HandoffRequest(BaseModel):
    from_agent: str
    to_agent: str
    prompt: str
    context: str = ""
    session_key: str = ""


class HandoffResult(BaseModel):
    from_agent: str
    to_agent: str
    prompt: str
    response: str
    success: bool
    error: str = ""
