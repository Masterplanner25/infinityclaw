"""KnowledgeInjector — formats retrieved chunks for system prompt injection."""
from __future__ import annotations

from pathlib import Path

from .ingestion import Chunk


class KnowledgeInjector:
    """Formats a list of Chunk objects into a system prompt section."""

    def build_block(self, chunks: list[Chunk]) -> str:
        if not chunks:
            return ""
        parts = ["## Relevant Knowledge"]
        for chunk in chunks:
            source = Path(chunk.source_file).name
            parts.append(f"**[{source}]**\n{chunk.content}")
        return "\n\n".join(parts)
