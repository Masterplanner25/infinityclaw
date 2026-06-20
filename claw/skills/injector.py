"""SkillsInjector — formats the skills list for the system prompt."""
from __future__ import annotations

from .loader import SkillManifest


class SkillsInjector:
    """Produces the skills section of the system prompt."""

    def build_block(self, skills: list[SkillManifest]) -> str:
        if not skills:
            return ""

        lines = ["## Skills\n"]
        lines.append("You have access to the following skill modules:\n")
        for skill in skills:
            line = f"- **{skill.name}** (`{skill.id}`): {skill.description}"
            if skill.tools:
                line += f" — tools: {', '.join(skill.tools)}"
            lines.append(line)

        return "\n".join(lines)
