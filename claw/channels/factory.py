"""Build channel adapters from ``[channels.extra.<name>]`` config.

Why this exists: the five external adapters (`claw_telegram`, `claw_discord`, `claw_slack`,
`claw_matrix`, `claw_signal`) were written and packaged, and `ClawGateway.register_adapter`
existed — but nothing ever called it, and `config.channels.extra` was read by `claw doctor` only.
Enabling a channel in `claw.toml` therefore did nothing at all: the gateway started with WebChat
and reported "1 channel(s)". This module is the missing step between the two.

Each builder resolves its secret from the config block first, then a well-known env var, so a
token can live in `.env` and never in a config file. A block that is present but unusable
(missing token, adapter package not installed) is reported and SKIPPED — one broken channel must
not stop the gateway, and the log must say which one and why. A channel is never silently absent:
every block in `extra` produces either a registered adapter or a warning naming it.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ChannelConfigError(ValueError):
    """A channel block is present but cannot produce an adapter."""


def _require(block: dict[str, Any], key: str, env: str, channel: str) -> str:
    value = str(block.get(key) or os.environ.get(env) or "").strip()
    if not value:
        raise ChannelConfigError(
            f"{channel}: no {key!r} in [channels.extra.{channel}] and ${env} is unset"
        )
    return value


def _as_str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _build_telegram(block: dict[str, Any]):
    from claw_telegram import TelegramAdapter

    return TelegramAdapter(
        _require(block, "token", "TELEGRAM_BOT_TOKEN", "telegram"),
        require_mention=bool(block.get("require_mention", True)),
        allowed_users=_as_str_list(
            block.get("allowed_users", os.environ.get("TELEGRAM_ALLOWED_USERS"))
        ),
    )


def _build_discord(block: dict[str, Any]):
    from claw_discord import DiscordAdapter

    return DiscordAdapter(
        _require(block, "token", "DISCORD_BOT_TOKEN", "discord"),
        require_mention=bool(block.get("require_mention", True)),
        allowed_guilds=[int(g) for g in _as_str_list(block.get("guild_ids"))],
    )


def _build_slack(block: dict[str, Any]):
    from claw_slack import SlackAdapter

    return SlackAdapter(
        _require(block, "bot_token", "SLACK_BOT_TOKEN", "slack"),
        _require(block, "app_token", "SLACK_APP_TOKEN", "slack"),
        require_mention=bool(block.get("require_mention", True)),
    )


def _build_matrix(block: dict[str, Any]):
    from claw_matrix import MatrixAdapter

    return MatrixAdapter(
        _require(block, "homeserver", "MATRIX_HOMESERVER", "matrix"),
        _require(block, "user_id", "MATRIX_USER_ID", "matrix"),
        password=str(block.get("password") or os.environ.get("MATRIX_PASSWORD") or ""),
        access_token=str(block.get("access_token") or os.environ.get("MATRIX_ACCESS_TOKEN") or ""),
        require_mention=bool(block.get("require_mention", True)),
        store_path=str(block.get("store_path") or ""),
    )


def _build_signal(block: dict[str, Any]):
    from claw_signal import SignalAdapter

    return SignalAdapter(
        _require(block, "phone", "SIGNAL_PHONE", "signal"),
        cli_path=str(block.get("cli_path") or "signal-cli"),
        data_path=str(block.get("data_path") or ""),
    )


BUILDERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "telegram": _build_telegram,
    "discord": _build_discord,
    "slack": _build_slack,
    "matrix": _build_matrix,
    "signal": _build_signal,
}


def build_extra_adapters(extra: dict[str, Any]) -> list[Any]:
    """Adapters for every usable block in ``config.channels.extra``.

    A block may carry ``enabled = false`` to stay configured but off. Anything else that cannot
    be built is logged (with the channel name and the reason) and skipped.
    """
    adapters: list[Any] = []
    for name, block in (extra or {}).items():
        if not isinstance(block, dict):
            logger.warning("[channels] %s: expected a config table, got %s — skipped",
                           name, type(block).__name__)
            continue
        if block.get("enabled") is False:
            logger.info("[channels] %s: configured but enabled = false — skipped", name)
            continue
        builder = BUILDERS.get(name.lower())
        if builder is None:
            logger.warning("[channels] %s: no adapter for this channel (known: %s) — skipped",
                           name, ", ".join(sorted(BUILDERS)))
            continue
        try:
            adapters.append(builder(block))
        except ChannelConfigError as exc:
            logger.warning("[channels] %s", exc)
        except ImportError as exc:
            logger.warning("[channels] %s: adapter package not importable (%s) — skipped",
                           name, exc)
        except Exception as exc:  # noqa: BLE001 — one bad channel never stops the gateway
            logger.warning("[channels] %s: could not be built (%s) — skipped", name, exc)
    return adapters
