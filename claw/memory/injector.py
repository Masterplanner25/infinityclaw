"""MemoryInjector — formats recalled MemoryNodes into a system prompt block."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nodus_memory import MemoryNode


class MemoryInjector:
    """Converts a list of recalled MemoryNodes into a system prompt section."""

    def build_block(self, nodes: "list[MemoryNode]") -> str:
        if not nodes:
            return ""
        lines = ["## Relevant Memories", ""]
        for node in nodes:
            tags_str = f" [{', '.join(node.tags)}]" if node.tags else ""
            date_str = node.created_at.strftime("%Y-%m-%d") if node.created_at else ""
            header = f"- [{node.memory_type}{tags_str}]"
            if date_str:
                header += f" ({date_str})"
            lines.append(f"{header} {node.content}")
        return "\n".join(lines)
