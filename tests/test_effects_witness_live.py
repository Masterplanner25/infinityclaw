"""SUBSTRATE-WITNESS-1 — the witness, live: Claw's delivery through the runtime's real chokepoint.

Runs only with ``AINDY_DATABASE_URL`` pointing at a Postgres the runtime's schema has been
bootstrapped on (``aindy-runtime bootstrap-schema``). Nothing is mocked below the seam: the real
``register_tool`` / ``mint_token`` / ``execute_tool`` / effect ledger, on real rows. The channel
adapter is the only stand-in, and it is the thing being protected: it counts how many times it
was asked to send.

What it proves, in the runtime entry's own words: capability metadata is derivable (a token is
minted from the tool's declaration and admits it); the ledger survives a real tool result (the
row completes ``success`` with the delivery receipt); and a DUPLICATE of an externally visible
effect is refused — the adapter sends once, the second call returns ``idempotent_replay``. The
counter ``aindy_effect_gate_outcomes_total`` moves, which is the number ``IDEM-11``'s soak has
been waiting to read.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

DATABASE_URL = os.environ.get("AINDY_DATABASE_URL", "")
CLAW_USER_ID = os.environ.get("AINDY_CLAW_USER_ID", "")  # a `users` row on that database
pytestmark = pytest.mark.skipif(
    not (DATABASE_URL.startswith("postgresql") and CLAW_USER_ID),
    reason="the witness needs AINDY_DATABASE_URL = a bootstrapped Postgres and AINDY_CLAW_USER_ID = a user on it",
)


class _CountingAdapter:
    channel_id = "witness"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    async def send(self, content: str, peer_id: str, **kwargs) -> None:
        self.sent.append((content, peer_id, kwargs))


def _gate_sample(label: str) -> float:
    from AINDY.platform_layer.metrics import REGISTRY

    return REGISTRY.get_sample_value("aindy_effect_gate_outcomes_total", {"outcome": label}) or 0.0


async def test_a_duplicate_delivery_is_refused_by_the_runtime_and_the_adapter_sends_once():
    from claw.aindy.effects import TOOL_NAME, AINDYEffectSeam, message_key
    from claw.channels.registry import ChannelAdapterRegistry

    registry = ChannelAdapterRegistry()
    adapter = _CountingAdapter()
    registry.register(adapter)
    seam = AINDYEffectSeam(user_id=CLAW_USER_ID, database_url=DATABASE_URL, registry=registry)
    seam.start(asyncio.get_running_loop())

    session = f"witness:{uuid.uuid4()}"
    key = message_key(session, "turn-1", 0)
    reserved_before, replayed_before = _gate_sample("reserved"), _gate_sample("replayed")

    first = await seam.send(channel_id="witness", peer_id="peer-1", content="hello, witness",
                            session_key=session, message_key=key)
    assert first["success"] is True and first["result"]["delivered"] is True, first
    assert not first.get("idempotent_replay")

    # the retry — same session, same message key: what a crashed-after-send re-drive would do
    second = await seam.send(channel_id="witness", peer_id="peer-1", content="hello, witness",
                             session_key=session, message_key=key)
    assert second["success"] is True and second.get("idempotent_replay") is True, second

    # ★ the effect the user would notice: one message, not two
    assert [c for c, _, _ in adapter.sent] == ["hello, witness"], adapter.sent

    # a DIFFERENT message in the same session is a different effect and goes out
    third = await seam.send(channel_id="witness", peer_id="peer-1", content="second message",
                            session_key=session, message_key=message_key(session, "turn-1", 1))
    assert third["success"] is True and not third.get("idempotent_replay")
    assert len(adapter.sent) == 2

    # the ledger row: real, completed, carrying the receipt
    from AINDY.db.database import SessionLocal
    from AINDY.db.models.effect_record import EffectRecord

    db = SessionLocal()
    try:
        rows = (
            db.query(EffectRecord)
            .filter(EffectRecord.action_type == TOOL_NAME, EffectRecord.tenant_id == CLAW_USER_ID)
            .order_by(EffectRecord.created_at.desc())
            .limit(2)
            .all()
        )
    finally:
        db.close()
    assert len(rows) == 2
    assert {r.status for r in rows} == {"success"}
    assert any((r.result_payload or {}).get("result", {}).get("message_key") == key for r in rows)

    # the counter IDEM-11's soak has been waiting to read
    assert _gate_sample("reserved") >= reserved_before + 2
    assert _gate_sample("replayed") >= replayed_before + 1


async def test_without_the_seam_a_retry_duplicates_the_message():
    """The control: the pre-witness path, same retry, two messages. If this ever fails, the
    adapter grew its own dedup and the witness above would be proving the wrong thing."""
    from claw.channels.registry import ChannelAdapterRegistry

    registry = ChannelAdapterRegistry()
    adapter = _CountingAdapter()
    registry.register(adapter)
    await registry.send("witness", "hello, control", "peer-1")
    await registry.send("witness", "hello, control", "peer-1")
    assert len(adapter.sent) == 2
