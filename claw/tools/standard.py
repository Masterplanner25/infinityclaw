"""Standard tool implementations — file I/O and session tools."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .registry import ToolRegistry

if TYPE_CHECKING:
    from claw.sessions.manager import ClawSessionManager

logger = logging.getLogger(__name__)


def register_standard_tools(
    registry: ToolRegistry,
    workspace_dir: str = "",
    session_manager: "ClawSessionManager | None" = None,
) -> None:
    """Register all standard Claw tools into *registry*."""
    workspace = Path(workspace_dir).expanduser() if workspace_dir else Path.cwd()
    _register_file_tools(registry, workspace)
    _register_browser_tools(registry)
    if session_manager:
        _register_session_tools(registry, session_manager)


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

def _register_file_tools(registry: ToolRegistry, workspace: Path) -> None:
    async def read_file(inp: dict) -> str:
        path = _safe_path(workspace, inp["path"])
        if not path.exists():
            return f"File not found: {inp['path']}"
        return path.read_text(encoding="utf-8")

    async def write_file(inp: dict) -> str:
        path = _safe_path(workspace, inp["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["content"], encoding="utf-8")
        return f"Written {len(inp['content'])} bytes to {inp['path']}"

    async def list_files(inp: dict) -> str:
        rel = inp.get("path", ".")
        target = _safe_path(workspace, rel)
        if not target.exists():
            return f"Directory not found: {rel}"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [f"{'DIR ' if e.is_dir() else '    '}{e.name}" for e in entries]
        return "\n".join(lines) or "(empty)"

    registry.register(
        "read_file",
        "Read the content of a file in the workspace.",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path from workspace root"}},
            "required": ["path"],
        },
        read_file,
    )

    registry.register(
        "write_file",
        "Write content to a file in the workspace, creating it if needed.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        write_file,
    )

    registry.register(
        "list_files",
        "List files and directories at a path in the workspace.",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path (default: workspace root)"}},
            "required": [],
        },
        list_files,
    )


# ---------------------------------------------------------------------------
# Browser tool
# ---------------------------------------------------------------------------

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_DEFAULT_MAX_CHARS = 8000


def _register_browser_tools(registry: ToolRegistry) -> None:
    async def browser_fetch(inp: dict) -> str:
        import re
        import httpx

        url = inp.get("url", "").strip()
        if not url:
            return "error: url is required"
        if not url.startswith(("http://", "https://")):
            return "error: url must start with http:// or https://"
        max_chars = int(inp.get("max_chars", _DEFAULT_MAX_CHARS))

        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _BROWSER_UA},
                follow_redirects=True,
                timeout=15,
            ) as client:
                resp = await client.get(url)

            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                text = resp.text
            elif "html" in content_type or not content_type:
                # Strip HTML tags, collapse whitespace
                text = re.sub(r"<style[^>]*>.*?</style>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"[ \t]+", " ", text)
                text = re.sub(r"\n{3,}", "\n\n", text)
                text = text.strip()
            else:
                text = resp.text

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[truncated — {len(resp.text)} chars total]"
            return f"[{resp.status_code} {url}]\n\n{text}"

        except httpx.TimeoutException:
            return f"error: request timed out fetching {url}"
        except Exception as exc:
            return f"error: {exc}"

    registry.register(
        "browser_fetch",
        (
            "Fetch the content of a URL and return it as plain text. "
            "Use this to look up web pages, documentation, or APIs. "
            "HTML is automatically stripped to readable text."
        ),
        {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must start with http:// or https://).",
                },
                "max_chars": {
                    "type": "integer",
                    "description": f"Maximum characters to return (default {_DEFAULT_MAX_CHARS}).",
                    "default": _DEFAULT_MAX_CHARS,
                },
            },
            "required": ["url"],
        },
        browser_fetch,
    )


def _safe_path(workspace: Path, rel: str) -> Path:
    """Resolve *rel* under *workspace*, preventing path traversal."""
    target = (workspace / rel).resolve()
    workspace_resolved = workspace.resolve()
    if not str(target).startswith(str(workspace_resolved)):
        raise ValueError(f"Path {rel!r} is outside the workspace")
    return target


# ---------------------------------------------------------------------------
# Session tools (wired if session_manager is provided)
# ---------------------------------------------------------------------------

def _register_session_tools(registry: ToolRegistry, sm: "ClawSessionManager") -> None:
    async def sessions_list(inp: dict) -> str:
        keys = sm.all_keys()
        if not keys:
            return "No active sessions."
        return "\n".join(keys)

    async def session_history(inp: dict) -> str:
        key = inp["session_key"]
        messages = sm.get_messages(key)
        if not messages:
            return f"No messages in session {key!r}"
        lines = []
        for m in messages[-20:]:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            lines.append(f"[{role}] {str(content)[:200]}")
        return "\n".join(lines)

    registry.register(
        "sessions_list",
        "List all active session keys.",
        {"type": "object", "properties": {}, "required": []},
        sessions_list,
    )

    registry.register(
        "session_history",
        "Get recent message history for a session.",
        {
            "type": "object",
            "properties": {"session_key": {"type": "string"}},
            "required": ["session_key"],
        },
        session_history,
    )
