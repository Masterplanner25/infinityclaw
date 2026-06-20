"""KnowledgeRetriever — async wrapper around KnowledgeIndex."""
from __future__ import annotations

import asyncio

from .index import KnowledgeIndex
from .ingestion import Chunk


class KnowledgeRetriever:
    """Retrieves relevant chunks for a turn query without blocking the event loop."""

    def __init__(self, index: KnowledgeIndex, top_k: int = 5) -> None:
        self._index = index
        self._top_k = top_k

    async def retrieve(self, query: str, workspace_id: str) -> list[Chunk]:
        return await asyncio.to_thread(
            self._index.search, query, workspace_id, self._top_k
        )
