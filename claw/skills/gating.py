"""SkillGate — filters skills by allow/deny lists."""
from __future__ import annotations

from .loader import SkillManifest


class SkillGate:
    """Filters a skill list against allow/deny configuration.

    - allow=[]: all skills pass
    - allow=["a","b"]: only a and b pass
    - deny=["x"]: x is removed regardless of allow list
    """

    def __init__(self, allow: list[str] | None = None, deny: list[str] | None = None) -> None:
        self._allow = set(allow or [])
        self._deny = set(deny or [])

    def filter(self, skills: list[SkillManifest]) -> list[SkillManifest]:
        result = []
        for skill in skills:
            if skill.id in self._deny:
                continue
            if self._allow and "*" not in self._allow and skill.id not in self._allow:
                continue
            result.append(skill)
        return result
