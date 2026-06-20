"""ContextCompactor — summarizes old messages to prevent context overflow."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.agents.turn import ConversationalTurn

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "You are summarizing a conversation for context compression. "
    "Produce a concise, factual summary of the key points, decisions, "
    "and information exchanged. Write in third person. Be brief."
)


class ContextCompactor:
    """Compacts a message list by summarizing the oldest messages.

    When ``len(messages) >= threshold``, the oldest ``keep_recent``
    messages are summarized into a single synthetic user message:

        [Summary of prior conversation: ...]

    This keeps the active context within the LLM's window while
    preserving continuity via the summary.
    """

    def __init__(self, threshold: int = 40, keep_recent: int = 20) -> None:
        self._threshold = threshold
        self._keep_recent = keep_recent

    def needs_compaction(self, messages: list[dict]) -> bool:
        return len(messages) >= self._threshold

    async def compact(
        self,
        messages: list[dict],
        turn: "ConversationalTurn",
    ) -> list[dict]:
        """Return a compacted message list.

        The oldest messages are sent to the LLM for summarization.
        The result replaces them with a single summary message.
        """
        if not self.needs_compaction(messages):
            return messages

        n_to_summarize = len(messages) - self._keep_recent
        old_messages = messages[:n_to_summarize]
        recent_messages = messages[n_to_summarize:]

        logger.info(
            "[compactor] compacting %d old messages (keeping %d recent)",
            len(old_messages), len(recent_messages),
        )

        summary_text = await self._summarize(old_messages, turn)
        summary_message = {
            "role": "user",
            "content": f"[Summary of prior conversation: {summary_text}]",
        }
        compacted = [summary_message] + recent_messages
        logger.info("[compactor] compacted to %d messages", len(compacted))
        return compacted

    async def _summarize(self, messages: list[dict], turn: "ConversationalTurn") -> str:
        """Call the LLM to summarize *messages*."""
        transcript = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
            if isinstance(m.get("content"), str)
        )
        try:
            result = await turn.run(
                messages=[{"role": "user", "content": f"Summarize this conversation:\n\n{transcript}"}],
                system=_SUMMARY_PROMPT,
                max_tokens=512,
                temperature=0.3,
            )
            return result.get("content", "").strip() or "[summary unavailable]"
        except Exception as exc:
            logger.warning("[compactor] summarization failed: %s", exc)
            return "[summary unavailable]"
