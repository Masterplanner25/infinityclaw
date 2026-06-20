"""SkillLoader — discovers SKILL.md skill directories from 3 locations."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillManifest:
    """Parsed metadata from a skill's SKILL.md."""
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    tools: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    source: str = ""   # "bundled" | "managed" | "workspace"
    path: Path = field(default_factory=Path)
    raw_md: str = ""


class SkillLoader:
    """Discovers and loads skills from three locations (precedence order):

    1. workspace/skills/  (agent-local, highest precedence)
    2. managed/           (~/.claw/skills — user-installed via ClawHub)
    3. bundled/           (claw/skills/ — shipped with Claw)
    """

    def __init__(self, state_dir: str = "~/.claw", extra_dirs: list[str] | None = None) -> None:
        self._state_dir = Path(state_dir).expanduser()
        self._extra_dirs = [Path(d).expanduser() for d in (extra_dirs or [])]

    def load(self, agent_id: str = "", workspace_dir: str = "") -> list[SkillManifest]:
        """Discover all skills visible to *agent_id*, respecting precedence.

        Later entries in the search order override earlier ones by id.
        """
        search = self._build_search(agent_id, workspace_dir)
        seen: dict[str, SkillManifest] = {}

        for source_label, skills_dir in reversed(search):  # lower precedence first
            if not skills_dir.exists():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                manifest_path = skill_dir / "SKILL.md"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = _parse_skill_md(manifest_path, source_label)
                    seen[manifest.id] = manifest
                except Exception as exc:
                    logger.warning("[skills] failed to load %s: %s", skill_dir, exc)

        skills = list(seen.values())
        logger.debug("[skills] loaded %d skill(s)", len(skills))
        return skills

    def _build_search(self, agent_id: str, workspace_dir: str) -> list[tuple[str, Path]]:
        """Return [(label, path)] in ascending precedence order."""
        # Package bundled dir (lowest)
        pkg_root = Path(__file__).parent.parent.parent
        search = [
            ("bundled", pkg_root / "skills"),
            ("managed", self._state_dir / "skills"),
        ]
        for d in self._extra_dirs:
            search.append(("extra", d))
        if workspace_dir:
            search.append(("workspace", Path(workspace_dir).expanduser() / "skills"))
        if agent_id:
            agent_skills = self._state_dir / "agents" / agent_id / "workspace" / "skills"
            search.append(("workspace", agent_skills))
        return search


def _parse_skill_md(path: Path, source: str) -> SkillManifest:
    raw = path.read_text(encoding="utf-8")
    skill_id = _extract(raw, "id") or path.parent.name
    name = _extract(raw, "name") or skill_id
    description = _extract_description(raw)
    version = _extract(raw, "version") or "0.1.0"
    tools = _extract_list(raw, "tools")
    triggers = _extract_list(raw, "triggers")

    return SkillManifest(
        id=skill_id,
        name=name,
        description=description,
        version=version,
        tools=tools,
        triggers=triggers,
        source=source,
        path=path.parent,
        raw_md=raw,
    )


def _extract(text: str, key: str) -> str:
    m = re.search(rf"^\s*{key}\s*[:=]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _extract_list(text: str, key: str) -> list[str]:
    value = _extract(text, key)
    if not value:
        return []
    return [v.strip() for v in re.split(r"[,\n]+", value) if v.strip()]


def _extract_description(text: str) -> str:
    # First non-heading, non-metadata paragraph
    lines = text.splitlines()
    desc_lines: list[str] = []
    in_desc = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if in_desc:
                break
            in_desc = True
            continue
        if in_desc and stripped and not re.match(r"^[a-z_]+\s*[:=]", stripped, re.IGNORECASE):
            desc_lines.append(stripped)
        elif in_desc and not stripped and desc_lines:
            break
    return " ".join(desc_lines)
