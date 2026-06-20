"""Config file loader — JSON/TOML with env-var overlay."""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .schema import ClawConfig, CredentialConfig


_SEARCH_NAMES = ["claw.json", "claw.toml", "openclaw.json", "openclaw.toml"]


def load_config(path: str | Path | None = None) -> ClawConfig:
    """Load config from *path*, auto-discover, or build from env vars.

    Resolution order:
    1. Explicit *path* argument
    2. ``CLAW_CONFIG`` env var
    3. Auto-search: claw.json / claw.toml / openclaw.json in cwd and ~/.claw/
    4. Bare env-var config (ANTHROPIC_API_KEY etc.)
    """
    load_dotenv()  # load .env if present

    raw: dict[str, Any] = {}

    config_path = _resolve_path(path)
    if config_path:
        raw = _read_file(config_path)

    _overlay_env(raw)
    _ensure_credential(raw)
    _assign_credential_ids(raw)

    return ClawConfig.model_validate(raw)


def _resolve_path(explicit: str | Path | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p

    env_path = os.environ.get("CLAW_CONFIG")
    if env_path:
        p = Path(env_path)
        if not p.exists():
            raise FileNotFoundError(f"CLAW_CONFIG path not found: {p}")
        return p

    search_dirs = [Path.cwd(), Path.home() / ".claw"]
    for d in search_dirs:
        for name in _SEARCH_NAMES:
            p = d / name
            if p.exists():
                return p

    return None


def _read_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return tomllib.loads(text)
    if suffix == ".json":
        text = _strip_comments(text)
        return json.loads(text)
    raise ValueError(f"Unsupported config format: {suffix}")


def _strip_comments(text: str) -> str:
    """Strip // and /* */ comments for basic JSON5 compatibility."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def _overlay_env(raw: dict[str, Any]) -> None:
    """Apply well-known env vars on top of file config."""
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        creds = raw.setdefault("credentials", [])
        primary = next((c for c in creds if c.get("provider") == "anthropic" and not c.get("priority")), None)
        if primary is None:
            creds.insert(0, {"provider": "anthropic", "api_key": api_key, "priority": 0})
        else:
            primary.setdefault("api_key", api_key)

    if token := os.environ.get("CLAW_GATEWAY_TOKEN"):
        raw.setdefault("gateway", {})["token"] = token

    if extra_creds_json := os.environ.get("CLAW_CREDENTIALS"):
        try:
            extras = json.loads(extra_creds_json)
            raw.setdefault("credentials", []).extend(extras)
        except json.JSONDecodeError:
            pass

    if aindy_key := os.environ.get("AINDY_API_KEY"):
        raw.setdefault("aindy", {})["api_key"] = aindy_key

    if aindy_url := os.environ.get("AINDY_URL"):
        raw.setdefault("aindy", {})["url"] = aindy_url


def _ensure_credential(raw: dict[str, Any]) -> None:
    """Guarantee at least one Anthropic credential exists."""
    creds = raw.get("credentials", [])
    if not creds:
        raise RuntimeError(
            "No LLM credentials configured. "
            "Set ANTHROPIC_API_KEY in .env or add credentials to claw.toml."
        )
    for c in creds:
        if not c.get("api_key"):
            raise RuntimeError(f"Credential {c.get('id', '?')} has no api_key")


def _assign_credential_ids(raw: dict[str, Any]) -> None:
    """Give sequential ids to credentials that don't have one."""
    for i, cred in enumerate(raw.get("credentials", [])):
        if not cred.get("id"):
            provider = cred.get("provider", "anthropic")
            cred["id"] = f"{provider}-{i}"
