"""Memory tools registered into ToolRegistry for agent use.

Tool handlers receive agent_id dynamically via a '_agent_id' key injected
by the gateway's per-turn scoped executor — the LLM never sees this field.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.memory.manager import MemoryManager
    from claw.tools.registry import ToolRegistry

_MEMORY_TOOLS = {"remember", "recall", "forget", "list_memories"}


def register_memory_tools(
    registry: "ToolRegistry",
    memory_manager: "MemoryManager",
) -> None:
    """Register memory tools (once) into the shared registry."""

    registry.register(
        name="remember",
        description=(
            "Store a memory for future recall. Use this when the user shares something "
            "important they want you to remember, or when you learn something useful. "
            "Returns the new memory's ID."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The memory to store — a clear, self-contained statement.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for later retrieval (e.g. ['preference', 'name']).",
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["insight", "decision", "outcome", "failure"],
                    "description": "Category of memory. Default: insight.",
                },
            },
            "required": ["content"],
        },
        handler=_make_remember_handler(memory_manager),
    )

    registry.register(
        name="recall",
        description=(
            "Search your stored memories for information relevant to the current query. "
            "Call this when you want to check what you already know about a topic."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tag filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_make_recall_handler(memory_manager),
    )

    registry.register(
        name="forget",
        description="Delete a stored memory by its ID.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The memory ID to delete (from remember or recall results).",
                },
            },
            "required": ["node_id"],
        },
        handler=_make_forget_handler(memory_manager),
    )

    registry.register(
        name="list_memories",
        description="List all stored memories (most recent first).",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
        handler=_make_list_handler(memory_manager),
    )


def is_memory_tool(name: str) -> bool:
    return name in _MEMORY_TOOLS


# ------------------------------------------------------------------ #
# Handler factories — agent_id comes from injected _agent_id key
# ------------------------------------------------------------------ #

def _make_remember_handler(memory_manager: "MemoryManager"):
    async def handler(input: dict) -> str:
        agent_id = input.get("_agent_id", "main")
        content = input.get("content", "").strip()
        if not content:
            return json.dumps({"error": "content is required"})
        tags = input.get("tags") or []
        memory_type = input.get("memory_type", "insight")
        try:
            node = await memory_manager.remember(
                agent_id, content, tags=tags, memory_type=memory_type,
            )
            return json.dumps({
                "id": node.id,
                "stored": True,
                "content": node.content[:80],
                "tags": node.tags,
                "memory_type": node.memory_type,
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_recall_handler(memory_manager: "MemoryManager"):
    async def handler(input: dict) -> str:
        agent_id = input.get("_agent_id", "main")
        query = input.get("query", "").strip()
        if not query:
            return json.dumps({"error": "query is required"})
        tags = input.get("tags") or None
        limit = int(input.get("limit", 5))
        try:
            nodes = await memory_manager.recall(agent_id, query, tags=tags, limit=limit)
            results = [
                {
                    "id": n.id,
                    "content": n.content,
                    "tags": n.tags,
                    "memory_type": n.memory_type,
                    "created_at": n.created_at.isoformat(),
                }
                for n in nodes
            ]
            return json.dumps({"results": results, "count": len(results)})
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_forget_handler(memory_manager: "MemoryManager"):
    async def handler(input: dict) -> str:
        agent_id = input.get("_agent_id", "main")
        node_id = input.get("node_id", "").strip()
        if not node_id:
            return json.dumps({"error": "node_id is required"})
        deleted = memory_manager.forget(agent_id, node_id)
        return json.dumps({"deleted": deleted, "node_id": node_id})
    return handler


def _make_list_handler(memory_manager: "MemoryManager"):
    async def handler(input: dict) -> str:
        agent_id = input.get("_agent_id", "main")
        limit = int(input.get("limit", 20))
        nodes = memory_manager.list_all(agent_id, limit=limit)
        results = [
            {
                "id": n.id,
                "content": n.content[:120],
                "tags": n.tags,
                "memory_type": n.memory_type,
                "created_at": n.created_at.isoformat(),
            }
            for n in nodes
        ]
        return json.dumps({"memories": results, "count": len(results)})
    return handler
