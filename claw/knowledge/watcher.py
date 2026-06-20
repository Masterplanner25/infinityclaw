"""KnowledgeWatcher — auto-reindexes workspace files when they change on disk."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.config.schema import AgentConfig, KnowledgeConfig
    from claw.knowledge.index import KnowledgeIndex

logger = logging.getLogger(__name__)


class KnowledgeWatcher:
    """Background task that watches agent workspace directories and re-indexes changed files.

    Requires the optional `watchfiles` package (pip install watchfiles).
    Silently exits if watchfiles is not installed.
    """

    def __init__(
        self,
        index: "KnowledgeIndex",
        config: "KnowledgeConfig",
        state_dir: Path,
    ) -> None:
        self._index = index
        self._config = config
        self._state_dir = state_dir

    async def watch(self, agents: list["AgentConfig"]) -> None:
        """Long-running background coroutine; cancel to stop."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            logger.info("[knowledge] watchfiles not installed — auto-reindex disabled")
            return

        from claw.knowledge.ingestion import ingest_file, SUPPORTED_EXTENSIONS
        from claw.workspace.bootstrapper import ALL_WORKSPACE_FILES

        excluded_names = frozenset(ALL_WORKSPACE_FILES)

        watch_dirs: list[str] = []
        for agent_cfg in agents:
            ws_dir = self._state_dir / "agents" / agent_cfg.id / "workspace"
            if ws_dir.exists():
                watch_dirs.append(str(ws_dir))

        if not watch_dirs:
            logger.debug("[knowledge] watcher: no workspace directories found")
            return

        logger.info(
            "[knowledge] watcher started watching %d dir(s): %s",
            len(watch_dirs),
            ", ".join(watch_dirs),
        )

        try:
            async for changes in awatch(*watch_dirs):
                for change, path_str in changes:
                    path = Path(path_str)
                    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if path.name in excluded_names:
                        continue

                    agent_id = self._owner_agent(path, agents)
                    if agent_id is None:
                        continue

                    if change == Change.deleted:
                        self._index.clear_source(path_str, agent_id)
                        logger.debug(
                            "[knowledge] watcher removed path=%s agent=%s",
                            path.name, agent_id,
                        )
                    else:
                        chunks = ingest_file(
                            path,
                            workspace_id=agent_id,
                            chunk_size=self._config.chunk_size,
                            chunk_overlap=self._config.chunk_overlap,
                        )
                        if chunks:
                            self._index.clear_source(path_str, agent_id)
                            self._index.upsert_many(chunks)
                            logger.debug(
                                "[knowledge] watcher reindexed path=%s agent=%s chunks=%d",
                                path.name, agent_id, len(chunks),
                            )
        except asyncio.CancelledError:
            logger.info("[knowledge] watcher stopped")

    def _owner_agent(self, path: Path, agents: list["AgentConfig"]) -> str | None:
        """Return the agent_id whose workspace directory contains *path*."""
        for agent_cfg in agents:
            ws_dir = self._state_dir / "agents" / agent_cfg.id / "workspace"
            try:
                path.relative_to(ws_dir)
                return agent_cfg.id
            except ValueError:
                continue
        return None
