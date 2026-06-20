"""ToolRegistry — maps tool names to async handler functions."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict], Awaitable[Any]]


class ToolRegistry:
    """Holds tool definitions (for the LLM) and handlers (for execution)."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: list[dict] = []

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: ToolHandler,
    ) -> None:
        if name in self._handlers:
            logger.debug("[tools] skipping duplicate registration of %r", name)
            return
        self._handlers[name] = handler
        self._definitions.append({
            "name": name,
            "description": description,
            "input_schema": input_schema,
        })

    def definitions(self) -> list[dict]:
        """Return Anthropic-format tool definition dicts."""
        return list(self._definitions)

    async def invoke(self, tool_name: str, tool_input: dict) -> Any:
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name!r}")
        logger.debug("[tools] invoking %s with %s", tool_name, list(tool_input.keys()))
        return await handler(tool_input)

    def executor(self) -> Callable[[str, dict], Awaitable[Any]]:
        """Return a (name, input) -> result callable for ConversationalTurn."""
        async def _exec(name: str, inp: dict) -> Any:
            return await self.invoke(name, inp)
        return _exec
