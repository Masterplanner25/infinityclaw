"""WorkspaceInitializer — creates agent state dirs and default workspace files."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_AGENTS_MD = """\
# Agent

You are Claw, a personal AI assistant powered by the Nodus ecosystem.
You are helpful, direct, and honest. You remember context across the conversation.
"""

_DEFAULT_SOUL_MD = """\
# Soul

Be concise. Be honest. Ask clarifying questions when the request is ambiguous.
Do not fabricate information. If you don't know something, say so.
"""


class WorkspaceInitializer:
    """Ensures the agent's workspace directory exists with sensible defaults."""

    def __init__(self, state_dir: str = "~/.claw") -> None:
        self._state_dir = Path(state_dir).expanduser()

    def initialize(self, agent_id: str) -> Path:
        """Create agent dirs and write default files if not present.

        Returns the agent workspace directory path.
        """
        agent_dir = self._state_dir / "agents" / agent_id
        workspace_dir = agent_dir / "workspace"
        sessions_dir = agent_dir / "sessions"

        for d in [workspace_dir, sessions_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._write_default(workspace_dir / "AGENTS.md", _DEFAULT_AGENTS_MD)
        self._write_default(workspace_dir / "SOUL.md", _DEFAULT_SOUL_MD)

        logger.info("[workspace] initialized agent=%s at %s", agent_id, workspace_dir)
        return workspace_dir

    def _write_default(self, path: Path, content: str) -> None:
        if not path.exists():
            path.write_text(content.strip() + "\n", encoding="utf-8")
            logger.debug("[workspace] wrote default %s", path.name)
