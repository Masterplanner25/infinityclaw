"""WorkspaceBootstrapper — loads agent workspace files into a dict."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files injected into the system prompt, in order
IDENTITY_FILES = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md"]
BOOT_FILES = ["HEARTBEAT.md", "BOOT.md", "BOOTSTRAP.md"]
ALL_WORKSPACE_FILES = IDENTITY_FILES + BOOT_FILES

# Per-file character limits (prevent runaway prompts)
_FILE_LIMITS: dict[str, int] = {
    "AGENTS.md": 8_000,
    "SOUL.md": 4_000,
    "IDENTITY.md": 4_000,
    "USER.md": 4_000,
    "TOOLS.md": 4_000,
    "HEARTBEAT.md": 2_000,
    "BOOT.md": 4_000,
    "BOOTSTRAP.md": 4_000,
}
_DEFAULT_LIMIT = 4_000


class WorkspaceBootstrapper:
    """Reads workspace markdown files and returns them as a name→content dict.

    Workspace directory precedence (first found wins per file):
    1. agent-specific dir  (~/.claw/agents/<id>/workspace)
    2. shared workspace    (configured workspace dir)
    3. global workspace    (~/.claw/workspace)
    """

    def __init__(self, state_dir: str = "~/.claw") -> None:
        self._state_dir = Path(state_dir).expanduser()

    def load(
        self,
        agent_id: str,
        *,
        agent_workspace: str = "",
        shared_workspace: str = "",
    ) -> dict[str, str]:
        """Load all workspace files for *agent_id*.

        Returns a dict of {filename: content} for files that exist and
        have non-empty content.
        """
        search_dirs = self._build_search_dirs(agent_id, agent_workspace, shared_workspace)
        result: dict[str, str] = {}

        for fname in ALL_WORKSPACE_FILES:
            content = self._find_file(fname, search_dirs)
            if content:
                result[fname] = content

        return result

    def _build_search_dirs(
        self,
        agent_id: str,
        agent_workspace: str,
        shared_workspace: str,
    ) -> list[Path]:
        dirs: list[Path] = []
        agent_dir = self._state_dir / "agents" / agent_id / "workspace"
        dirs.append(agent_dir)

        if agent_workspace:
            dirs.append(Path(agent_workspace).expanduser())
        if shared_workspace:
            dirs.append(Path(shared_workspace).expanduser())

        global_workspace = self._state_dir / "workspace"
        if global_workspace not in dirs:
            dirs.append(global_workspace)

        # Also check cwd/workspace for dev convenience
        dirs.append(Path.cwd() / "workspace")

        return [d for d in dirs if d.exists()]

    def _find_file(self, fname: str, dirs: list[Path]) -> str:
        limit = _FILE_LIMITS.get(fname, _DEFAULT_LIMIT)
        for d in dirs:
            p = d / fname
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8").strip()
                    if content:
                        if len(content) > limit:
                            content = content[:limit] + f"\n\n[...truncated at {limit} chars]"
                            logger.warning("[workspace] %s truncated to %d chars", fname, limit)
                        return content
                except OSError as exc:
                    logger.warning("[workspace] cannot read %s: %s", p, exc)
        return ""
