"""ConversationalTurn — streaming LLM loop with tool use and credential rotation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

import anthropic
from nodus_llm.failover import _classify_error
from nodus_llm.profile import CredentialStore

logger = logging.getLogger(__name__)


class ConversationalTurn:
    """Drives one agent turn: LLM call → (tool use loop) → streamed reply.

    Uses nodus_llm.CredentialStore for credential selection and cooldown
    tracking, but calls the Anthropic SDK directly for streaming + tool use
    (FailoverClient.chat() is non-streaming and tool-unaware).
    """

    def __init__(self, credential_store: CredentialStore) -> None:
        self._store = credential_store

    async def run(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict] | None = None,
        *,
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        model_override: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tool_executor: Optional[Callable[[str, dict], Awaitable[Any]]] = None,
    ) -> dict:
        """Run one conversational turn with streaming and optional tool use.

        Args:
            messages:       Conversation history as Anthropic-format dicts.
            system:         System prompt string.
            tools:          Anthropic tool definition dicts (or None).
            on_chunk:       Awaitable called for each streamed text chunk.
            model_override: Override the profile's model.
            max_tokens:     Max output tokens.
            temperature:    Sampling temperature.
            tool_executor:  Async callable(tool_name, tool_input) → result.

        Returns:
            {"role": "assistant", "content": "<full text response>"}
        """
        profiles = self._store.available()
        if not profiles:
            raise RuntimeError("No LLM credentials available — all profiles on cooldown")

        profile = profiles[0]
        client = anthropic.AsyncAnthropic(api_key=profile.api_key)
        model = model_override or profile.model or "claude-sonnet-4-6"

        current_messages = list(messages)
        full_text = ""

        try:
            while True:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": current_messages,
                }
                if tools:
                    kwargs["tools"] = tools

                async with client.messages.stream(**kwargs) as stream:
                    turn_text = ""
                    async for chunk in stream.text_stream:
                        turn_text += chunk
                        if on_chunk:
                            await on_chunk(chunk)

                    final = await stream.get_final_message()

                if final.stop_reason != "tool_use":
                    full_text = turn_text
                    break

                # --- tool use loop ---
                assistant_content = [
                    _serialize_block(b) for b in final.content
                ]
                current_messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    result_text = await _invoke_tool(block.name, block.input, tool_executor)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
                    logger.debug("[turn] tool=%s result_len=%d", block.name, len(result_text))

                current_messages.append({"role": "user", "content": tool_results})

        except Exception as exc:
            reason = _classify_error(exc)
            self._store.mark_cooldown(profile.id, reason)
            logger.warning("[turn] LLM error profile=%s reason=%s: %s", profile.id, reason, exc)
            raise

        self._store.mark_success(profile.id)
        return {"role": "assistant", "content": full_text}


def _serialize_block(block: Any) -> dict:
    """Convert an Anthropic content block to a serializable dict."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return {"type": block.type}


async def _invoke_tool(
    name: str,
    input_: dict,
    executor: Optional[Callable[[str, dict], Awaitable[Any]]],
) -> str:
    if executor is None:
        return f"[tool '{name}' not available]"
    try:
        result = await executor(name, input_)
        return str(result) if result is not None else ""
    except Exception as exc:
        logger.warning("[turn] tool %r raised: %s", name, exc)
        return f"[error in tool '{name}': {exc}]"
