"""SystemPromptBuilder — assembles the agent system prompt from workspace + skills."""
from __future__ import annotations

import datetime
import platform
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PromptContext:
    """All inputs needed to build a system prompt."""
    agent_id: str
    agent_name: str
    workspace_files: dict[str, str] = field(default_factory=dict)
    skills_block: str = ""
    tools_block: str = ""
    memories_block: str = ""   # injected by MemoryInjector before each turn
    extra_sections: list[tuple[str, str]] = field(default_factory=list)


class SystemPromptBuilder:
    """Builds the agent system prompt.

    Order:
    1. AGENTS.md / SOUL.md / IDENTITY.md (workspace identity files)
    2. USER.md (user profile)
    3. TOOLS.md (manual tool notes)
    4. Runtime metadata (time, host)
    5. Skills list
    6. Extra sections
    """

    _IDENTITY_ORDER = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md"]
    _BOOT_ORDER = ["HEARTBEAT.md", "BOOT.md", "BOOTSTRAP.md"]

    def build(self, ctx: PromptContext) -> str:
        sections: list[str] = []

        # Identity / workspace files in canonical order
        for fname in self._IDENTITY_ORDER:
            content = ctx.workspace_files.get(fname, "").strip()
            if content:
                sections.append(content)

        # Runtime metadata
        sections.append(self._runtime_block(ctx))

        # Boot files
        for fname in self._BOOT_ORDER:
            content = ctx.workspace_files.get(fname, "").strip()
            if content:
                sections.append(f"## {fname}\n{content}")

        # Relevant memories (recalled before the turn)
        if ctx.memories_block:
            sections.append(ctx.memories_block)

        # Skills
        if ctx.skills_block:
            sections.append(ctx.skills_block)

        # Tools manual notes
        if ctx.tools_block:
            sections.append(ctx.tools_block)

        # Caller-injected extras
        for title, body in ctx.extra_sections:
            sections.append(f"## {title}\n{body}")

        return "\n\n---\n\n".join(s for s in sections if s)

    def _runtime_block(self, ctx: PromptContext) -> str:
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B {day}, %Y").format(day=now.day)
        return (
            f"## Runtime\n"
            f"Agent: {ctx.agent_name or ctx.agent_id}\n"
            f"Date: {date_str}\n"
            f"Time: {now.strftime('%H:%M')} local\n"
            f"Host: {platform.node()}"
        )
