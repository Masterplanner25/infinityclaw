"""The AINDY effect seam, at the unit level — the runtime's collaborators faked at the seam.

The live witness (real runtime, real ledger, real Postgres) is `test_effects_witness_live.py`;
it is the evidence SUBSTRATE-WITNESS-1 asks for and it only runs with AINDY_DATABASE_URL set.
These tests pin the seam's own contract so a refactor cannot quietly stop routing delivery
through `execute_tool`: the gateway's `deliver()` goes through the seam when configured and to
the adapter when not; the seam passes tool name, args with the message key, run id and token;
a refused result raises; a replayed one is reported, not re-sent.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from claw.aindy.effects import TOOL_NAME, AINDYEffectSeam, DeliveryRefused, message_key


USER = "f33f40c2-9580-4c42-a281-2d507c4eddff"


def _seam(registry=None) -> AINDYEffectSeam:
    return AINDYEffectSeam(user_id=USER, database_url="postgresql://x/y", registry=registry or MagicMock())


def test_the_seam_refuses_no_database_sqlite_and_a_tenant_that_is_not_a_runtime_user():
    with pytest.raises(ValueError):
        AINDYEffectSeam(user_id=USER, database_url="", registry=MagicMock())
    with pytest.raises(ValueError, match="Postgres"):
        AINDYEffectSeam(user_id=USER, database_url="sqlite:///:memory:", registry=MagicMock())
    # the witness's first finding: the tenant is a UUID FK to `users`, not a label
    with pytest.raises(ValueError, match="runtime user's UUID"):
        AINDYEffectSeam(user_id="claw", database_url="postgresql://x/y", registry=MagicMock())


def test_message_key_is_stable_per_turn_and_block():
    assert message_key("s1", "t1", 0) == "s1:t1:0"
    assert message_key("s1", "t1", 0) == message_key("s1", "t1", 0)
    assert message_key("s1", "t1", 1) != message_key("s1", "t1", 0)


async def test_send_goes_through_execute_tool_with_the_key_the_run_and_the_token():
    seam = _seam()
    seam.started = True
    seam._session_factory = MagicMock(return_value=MagicMock())
    calls: list[dict] = []

    def _execute_tool(**kw):
        calls.append(kw)
        return {"success": True, "result": {"delivered": True}, "error": None}

    seam._execute_tool = _execute_tool
    seam._token_for = lambda session_key: ("run-1", {"execution_token": "tok", "run_id": "run-1"})

    result = await seam.send(channel_id="discord", peer_id="p1", content="hi", session_key="s1",
                             message_key="s1:t1:0", thread_id="th")
    assert result["result"] == {"delivered": True}
    (kw,) = calls
    assert kw["tool_name"] == TOOL_NAME and kw["run_id"] == "run-1" and kw["user_id"] == USER
    assert kw["execution_token"] == {"execution_token": "tok", "run_id": "run-1"}
    assert kw["args"] == {"channel_id": "discord", "peer_id": "p1", "content": "hi",
                          "message_key": "s1:t1:0", "thread_id": "th"}
    seam._session_factory.return_value.close.assert_called_once()


async def test_a_refused_delivery_raises_with_the_runtime_result():
    seam = _seam()
    seam.started = True
    seam._session_factory = MagicMock(return_value=MagicMock())
    seam._execute_tool = lambda **kw: {"success": False, "result": None, "error": "capability for claw.channel.send not granted",
                                       "failure_class": "permission"}
    seam._token_for = lambda session_key: ("run-1", {})
    with pytest.raises(DeliveryRefused) as exc:
        await seam.send(channel_id="c", peer_id="p", content="x", session_key="s", message_key="k")
    assert exc.value.result["failure_class"] == "permission"


async def test_a_replay_is_reported_and_not_an_error(caplog):
    seam = _seam()
    seam.started = True
    seam._session_factory = MagicMock(return_value=MagicMock())
    seam._execute_tool = lambda **kw: {"success": True, "result": None, "error": None, "idempotent_replay": True}
    seam._token_for = lambda session_key: ("run-1", {})
    result = await seam.send(channel_id="c", peer_id="p", content="x", session_key="s", message_key="k")
    assert result["idempotent_replay"] is True


async def test_the_tool_body_sends_through_the_registry_on_the_gateway_loop():
    registry = MagicMock()
    registry.send = AsyncMock()
    seam = _seam(registry)
    seam._loop = asyncio.get_running_loop()
    args = {"channel_id": "discord", "peer_id": "p1", "content": "hi", "message_key": "k", "thread_id": "th"}
    out = await asyncio.to_thread(seam._deliver, args, USER, None)
    registry.send.assert_awaited_once_with("discord", "hi", "p1", thread_id="th")
    assert out["delivered"] is True and out["message_key"] == "k"


async def test_the_gateway_delivers_through_the_seam_when_configured_else_the_registry():
    from claw.gateway.server import _deliver_via

    gateway = MagicMock()
    gateway.channel_registry.send = AsyncMock()
    gateway._effects = None
    await _deliver_via(gateway, "discord", "hi", "p1", session_key="s1", turn_id="t1", index=0, thread_id="th")
    gateway.channel_registry.send.assert_awaited_once_with("discord", "hi", "p1", thread_id="th")

    gateway._effects = MagicMock()
    gateway._effects.send = AsyncMock(return_value={"success": True})
    gateway.channel_registry.send.reset_mock()
    await _deliver_via(gateway, "discord", "hi", "p1", session_key="s1", turn_id="t1", index=2)
    gateway._effects.send.assert_awaited_once_with(channel_id="discord", peer_id="p1", content="hi",
                                                   session_key="s1", message_key="s1:t1:2", thread_id=None)
    gateway.channel_registry.send.assert_not_awaited()
