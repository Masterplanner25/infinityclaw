"""WorkspaceScanner — finds files eligible for knowledge indexing."""
from __future__ import annotations

from pathlib import Path

from claw.workspace.bootstrapper import ALL_WORKSPACE_FILES
from .ingestion import SUPPORTED_EXTENSIONS

# Identity and boot files are verbatim-injected by WorkspaceBootstrapper; skip them.
_EXCLUDED_NAMES: frozenset[str] = frozenset(ALL_WORKSPACE_FILES)


class WorkspaceScanner:
    """Scans a workspace directory for indexable files.

    Excludes identity/boot files (AGENTS.md, SOUL.md, etc.) since those are
    already verbatim-injected into the system prompt by WorkspaceBootstrapper.
    """

    def scan(self, workspace_dir: Path) -> list[Path]:
        """Return all indexable files in *workspace_dir* (non-recursive)."""
        if not workspace_dir.is_dir():
            return []
        results: list[Path] = []
        for path in sorted(workspace_dir.iterdir()):
            if (
                path.is_file()
                and path.name not in _EXCLUDED_NAMES
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ):
                results.append(path)
        return results
