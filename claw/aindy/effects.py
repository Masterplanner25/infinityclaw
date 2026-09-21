"""AINDY effect seam — Claw's outbound message delivery routed through aindy-runtime's tool seam.

Why this exists (runtime `TECH_DEBT.md`, ``SUBSTRATE-WITNESS-1``): Claw depended on the runtime
as a package and routed none of its effects through it. Its real effects — messages delivered to
Discord / Telegram / Slack / Matrix / Signal — ran straight through the channel adapters: no
capability token, no ``EffectRecord``, at-least-once with no dedup. A duplicate message is the
one effect a user *notices*, which makes delivery the right first slice: it is the consumer that
would see the guarantee break.

What this does, when ``[aindy] effects_backend = "aindy"``:

- registers ``claw.channel.send`` with the runtime's tool registry, declared ``EXACTLY_ONCE``,
  and the ``channel.send`` capability definition it requires;
- mints ONE scoped capability token per Claw session (``mint_token``, approval ``manual``, a
  one-step plan naming the tool) and refreshes it when it expires;
- sends every outbound message through ``execute_tool`` — the chokepoint: capability check →
  effect ledger → the adapter. A retry of the same message in the same session (same
  ``message_key``) is REFUSED by the ledger and returns ``idempotent_replay: True`` without the
  adapter being called.

What this is not: a second delivery mechanism. The adapter's ``send`` is still the effect; the
runtime mediates it. With the backend at ``"local"`` (the default) nothing here is imported and
delivery is what it was.

The runtime is embedded IN PROCESS and needs a real Postgres (``[aindy] database_url`` /
``AINDY_DATABASE_URL``) — the effect ledger is a table. SQLite under the runtime's test mode is
refused here on purpose: a witness that runs on the runtime's test-mode short-circuits proves
nothing (its own rule).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from claw.channels.registry import ChannelAdapterRegistry

logger = logging.getLogger(__name__)

TOOL_NAME = "claw.channel.send"
CAPABILITY = "channel.send"
_SEND_TIMEOUT_S = 60.0

_ARGS_SCHEMA = {
    "type": "object",
    "required": ["channel_id", "peer_id", "content", "message_key"],
    "properties": {
        "channel_id": {"type": "string"},
        "peer_id": {"type": "string"},
        "content": {"type": "string"},
        "message_key": {"type": "string"},
        "thread_id": {"type": "string"},
    },
}


class DeliveryRefused(RuntimeError):
    """The runtime refused the delivery (capability, ledger, or the adapter raised inside it)."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(str(result.get("error") or "delivery refused"))


class AINDYEffectSeam:
    """Routes ``ChannelAdapterRegistry.send`` through ``AINDY.agents.tool_registry.execute_tool``."""

    def __init__(self, *, user_id: str, database_url: str, registry: "ChannelAdapterRegistry") -> None:
        if not database_url:
            raise ValueError("[aindy] effects_backend = 'aindy' needs [aindy] database_url (or AINDY_DATABASE_URL)")
        if database_url.startswith("sqlite"):
            raise ValueError("[aindy] the effect seam needs Postgres: the effect ledger is a table, and the "
                             "runtime's SQLite test mode short-circuits the checks this seam exists to exercise")
        # ★ Found by the witness's first run: the runtime's tenant is a UUID FOREIGN KEY to its
        # `users` table (system_events.user_id, the effect ledger's attribution). A consumer
        # is a runtime USER, not a label -- the default `[aindy] user_id = "claw"` fails on the
        # first mediated effect (the required `capability.allowed` event cannot persist, so the
        # capability check fails). Refuse it here, at startup, with the reason.
        try:
            uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            raise ValueError(
                f"[aindy] user_id must be the runtime user's UUID (got {user_id!r}): the effect ledger "
                "attributes every effect to a `users` row. Register a user on the runtime and set its id."
            ) from None
        self._user_id = str(user_id)
        self._database_url = database_url
        self._registry = registry
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tokens: dict[str, tuple[str, dict[str, Any]]] = {}  # session_key -> (run_id, token)
        self._session_factory: Any = None
        self._execute_tool: Any = None
        self.started = False

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Embed the runtime: point it at the database, register the tool, keep the seam."""
        self._loop = loop
        os.environ["DATABASE_URL"] = self._database_url
        # MEB-0: the tool-path idempotency gate is opt-in in the runtime; this seam IS the opt-in.
        os.environ.setdefault("AINDY_TOOL_IDEMPOTENCY", "1")

        from AINDY.agents.tool_registry import TOOL_REGISTRY, execute_tool, register_tool
        from AINDY.db.database import SessionLocal
        from AINDY.platform_layer.registry import (
            register_capability_definition,
            register_tool_capabilities,
        )

        register_capability_definition(CAPABILITY, {
            "description": "Deliver a message to a peer on a connected Claw channel (external, user-visible).",
            "risk_level": "medium",
        })
        if TOOL_NAME not in TOOL_REGISTRY:
            register_tool(
                name=TOOL_NAME,
                risk="medium",
                description="Deliver one outbound message through a Claw channel adapter.",
                capability=CAPABILITY,
                required_capability=CAPABILITY,
                category="delivery",
                egress_scope="web",
                execution_guarantee="EXACTLY_ONCE",
                args_schema=_ARGS_SCHEMA,
            )(self._deliver)
        register_tool_capabilities(TOOL_NAME, [CAPABILITY])
        self._session_factory = SessionLocal
        self._execute_tool = execute_tool
        self.started = True
        logger.info("[aindy_effects] delivery routed through execute_tool (%s, EXACTLY_ONCE) user=%s",
                    TOOL_NAME, self._user_id)

    # ── the tool body: runs in a worker thread, inside execute_tool ─────────────

    def _deliver(self, args: dict[str, Any], user_id: str, db: Any) -> dict[str, Any]:
        assert self._loop is not None
        kwargs = {"thread_id": args["thread_id"]} if args.get("thread_id") else {}
        future = asyncio.run_coroutine_threadsafe(
            self._registry.send(args["channel_id"], args["content"], args["peer_id"], **kwargs),
            self._loop,
        )
        future.result(timeout=_SEND_TIMEOUT_S)
        return {
            "delivered": True,
            "channel_id": args["channel_id"],
            "peer_id": args["peer_id"],
            "message_key": args["message_key"],
            "delivered_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── the token: one per session, minted through the runtime's own path ───────

    def _token_for(self, session_key: str) -> tuple[str, dict[str, Any]]:
        from AINDY.agents.capability_service import mint_token, refresh_token, token_is_expired

        cached = self._tokens.get(session_key)
        if cached is not None:
            run_id, token = cached
            if not token_is_expired(token):
                return run_id, token
            refreshed = refresh_token(token)
            if refreshed is not None:
                self._tokens[session_key] = (run_id, refreshed)
                return run_id, refreshed
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"claw://session/{session_key}"))
        db = self._session_factory()
        try:
            token = mint_token(
                run_id=run_id,
                user_id=self._user_id,
                plan={"steps": [{"tool": TOOL_NAME, "args": {}, "risk_level": "medium", "description": "deliver"}]},
                db=db,
                approval_mode="manual",
            )
        finally:
            db.close()
        if token is None:
            raise DeliveryRefused({"success": False, "error": f"the runtime minted no token for {TOOL_NAME}"})
        self._tokens[session_key] = (run_id, token)
        return run_id, token

    # ── the seam: what the gateway and cron call instead of adapter.send ────────

    async def send(self, *, channel_id: str, peer_id: str, content: str, session_key: str,
                   message_key: str, thread_id: Optional[str] = None) -> dict[str, Any]:
        """Deliver through the chokepoint. Same ``(session, message_key)`` twice → replayed, not re-sent."""
        if not self.started:
            raise RuntimeError("AINDYEffectSeam.start() was not called")
        run_id, token = await asyncio.to_thread(self._token_for, session_key)
        args = {"channel_id": channel_id, "peer_id": peer_id, "content": content, "message_key": message_key}
        if thread_id:
            args["thread_id"] = str(thread_id)

        def _call() -> dict[str, Any]:
            db = self._session_factory()
            try:
                return self._execute_tool(
                    tool_name=TOOL_NAME, args=args, user_id=self._user_id, db=db,
                    run_id=run_id, execution_token=token,
                )
            finally:
                try:
                    db.close()
                except Exception:  # noqa: BLE001
                    pass

        result = await asyncio.to_thread(_call)
        if not result.get("success"):
            raise DeliveryRefused(result)
        if result.get("idempotent_replay"):
            logger.info("[aindy_effects] duplicate delivery refused by the ledger session=%s key=%s",
                        session_key, message_key)
        return result


def message_key(session_key: str, turn_id: str, index: int) -> str:
    """The dedup key of one outbound message: which turn, which block. Stable across a retry."""
    return f"{session_key}:{turn_id}:{index}"
