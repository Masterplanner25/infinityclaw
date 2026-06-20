"""ContextPruner — trims message history to stay within token limits."""
from __future__ import annotations


class ContextPruner:
    """Keeps message lists within configured bounds.

    Strategy: retain the system prompt (not in messages list), keep the most
    recent *max_messages* messages, always keeping the first user message if
    there is one (to anchor the conversation).
    """

    def __init__(self, max_messages: int = 200) -> None:
        self._max = max_messages

    def prune(self, messages: list[dict]) -> list[dict]:
        """Return a pruned copy of *messages* that fits within limits."""
        if len(messages) <= self._max:
            return messages

        # Always keep pairs (user+assistant) so the list stays valid
        keep = messages[-self._max:]
        # Ensure we don't start mid-pair with an assistant message
        if keep and keep[0].get("role") == "assistant":
            keep = keep[1:]
        return keep
