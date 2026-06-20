"""PermissionEnforcer — validates tool invocations against declared capabilities."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from claw.permissions.model import CapabilitySet

_FILESYSTEM_READ_TOOLS: frozenset[str] = frozenset({"read_file", "list_files"})
_FILESYSTEM_WRITE_TOOLS: frozenset[str] = frozenset({"write_file"})
_HTTP_TOOLS: frozenset[str] = frozenset({"browser_fetch"})


class PermissionDenied(Exception):
    """Raised when a tool call violates the agent's declared capability set."""


class PermissionEnforcer:
    """Validates tool calls against an agent's CapabilitySet.

    Create one per turn (capabilities may change across reloads), passing
    the agent's configured CapabilitySet or None for full access.
    """

    def __init__(self, capabilities: Optional[CapabilitySet] = None) -> None:
        self._caps = capabilities or CapabilitySet()

    def filter_tool_definitions(self, definitions: list[dict]) -> list[dict]:
        """Remove definitions for tools blocked by tool_use policy."""
        return [d for d in definitions if not self._tool_blocked(d.get("name", ""))]

    def check_tool_call(self, name: str, inp: dict) -> None:
        """Raise PermissionDenied if this tool call is not permitted.

        Call this before executing any tool handler.
        """
        if self._tool_blocked(name):
            raise PermissionDenied(f"Tool '{name}' is not permitted for this agent")

        if name in _HTTP_TOOLS:
            self._check_http(inp.get("url", ""))

        if name in _FILESYSTEM_READ_TOOLS:
            self._check_filesystem("read", inp.get("path", ""))
        elif name in _FILESYSTEM_WRITE_TOOLS:
            self._check_filesystem("write", inp.get("path", ""))

    # ------------------------------------------------------------------
    # Internal validators
    # ------------------------------------------------------------------

    def _tool_blocked(self, name: str) -> bool:
        perm = self._caps.tool_use
        if name in perm.deny:
            return True
        if "*" in perm.allow:
            return False
        return name not in perm.allow

    def _check_http(self, url: str) -> None:
        http = self._caps.external_http
        if not http.enabled:
            raise PermissionDenied("external_http.enabled is false for this agent")

        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
        except Exception:
            raise PermissionDenied(f"Malformed URL: {url!r}")

        if _is_private_host(host):
            raise PermissionDenied(
                f"Access to private network address is blocked (host={host!r})"
            )

        for pattern in http.denylist:
            if pattern in url:
                raise PermissionDenied(
                    f"URL '{url}' matches HTTP denylist entry '{pattern}'"
                )

        if http.allowlist:
            for pattern in http.allowlist:
                if url.startswith(pattern):
                    return
            raise PermissionDenied(f"URL '{url}' is not in the HTTP allowlist")

    def _check_filesystem(self, operation: str, path_str: str) -> None:
        fs = self._caps.filesystem
        # filesystem.read/write guard paths *outside* the workspace.
        # Workspace-scoped tools (read_file/write_file) are always permitted;
        # _safe_path in standard.py already enforces workspace confinement.
        if operation == "read" and not fs.read:
            return  # workspace-scoped reads are always allowed
        if operation == "write" and not fs.write:
            return  # workspace-scoped writes are always allowed

        # If explicit paths are declared, the resolved path must fall within one.
        if fs.paths and path_str:
            resolved = Path(path_str).resolve()
            for allowed in fs.paths:
                allowed_p = Path(allowed).expanduser().resolve()
                try:
                    resolved.relative_to(allowed_p)
                    return
                except ValueError:
                    continue
            raise PermissionDenied(
                f"Path '{path_str}' is outside declared filesystem.paths"
            )


def _is_private_host(host: str) -> bool:
    """Return True if *host* is a loopback or RFC-1918 private address."""
    host = host.lower().strip(".")
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return True
    # IPv6 loopback
    if host in ("::1", "[::1]"):
        return True
    # Loopback and RFC-1918 ranges
    if host.startswith(("127.", "10.", "192.168.")):
        return True
    # 172.16.0.0/12 — 172.16.x.x through 172.31.x.x
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    return False
