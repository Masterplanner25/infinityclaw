"""The AINDY bridge's wire shape — pinned, because it was wrong for months and nothing noticed.

aindy-sdk 1.0.0's `events.emit` sends `{"type": ...}` where the runtime's `sys.v1.event.emit`
requires `event_type`. Every turn-lifecycle event this bridge ever emitted 422'd, and
`_emit_aindy` logged it at DEBUG. These tests pin the two things that fix that: the bridge calls
the syscall with the key the runtime reads, and a failing emit is a WARNING (once per type).

Mutation-checked: revert `emit_event` to `self._sync.events.emit` → the first test fails on the
call it must not make; drop the once-per-type set → the warning test fails on the count.
"""
from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sdk_stub(monkeypatch):
    """A stand-in `aindy_sdk` module so the bridge can be built without a server."""
    client = MagicMock(name="AINDYClient")
    client.syscalls.call.return_value = {"status": "success", "data": {"event_id": "e1"}}
    module = types.ModuleType("aindy_sdk")
    module.AINDYClient = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "aindy_sdk", module)
    return client


async def test_emit_event_calls_the_syscall_with_event_type_not_the_sdk_method(sdk_stub):
    from claw.aindy.client import _AsyncAINDYClient

    bridge = _AsyncAINDYClient("http://runtime:8000", "aindy_key")
    result = await bridge.emit_event("sys.v1.claw.turn.start", {"agent_id": "a1"})

    sdk_stub.syscalls.call.assert_called_once_with(
        "sys.v1.event.emit",
        {"event_type": "sys.v1.claw.turn.start", "payload": {"agent_id": "a1"}},
    )
    sdk_stub.events.emit.assert_not_called()
    assert result["data"]["event_id"] == "e1"


async def test_emit_event_with_no_payload_sends_an_empty_dict(sdk_stub):
    from claw.aindy.client import _AsyncAINDYClient

    await _AsyncAINDYClient("http://runtime:8000", "k").emit_event("sys.v1.claw.turn.error")
    _, sent = sdk_stub.syscalls.call.call_args.args
    assert sent == {"event_type": "sys.v1.claw.turn.error", "payload": {}}


async def test_a_failing_emit_warns_once_per_event_type(caplog):
    from claw.gateway import server

    server._AINDY_EMIT_WARNED.clear()

    class _Broken:
        async def emit_event(self, event_type, payload):
            raise RuntimeError("422 Unprocessable Entity")

    with caplog.at_level(logging.DEBUG, logger="claw.gateway.server"):
        await server._emit_aindy(_Broken(), "sys.v1.claw.turn.start", {})
        await server._emit_aindy(_Broken(), "sys.v1.claw.turn.start", {})
        await server._emit_aindy(_Broken(), "sys.v1.claw.turn.complete", {})

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2, warnings
    assert "sys.v1.claw.turn.start" in warnings[0] and "sys.v1.claw.turn.complete" in warnings[1]
    assert sum(1 for r in caplog.records if r.levelno == logging.DEBUG and "skipped" in r.getMessage()) == 1
