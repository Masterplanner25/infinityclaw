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
from aindy_sdk.events import EventAPI  # the real class, imported before the stub replaces the module


@pytest.fixture
def sdk_stub(monkeypatch):
    """A stand-in `aindy_sdk` module so the bridge can be built without a server."""
    client = MagicMock(name="AINDYClient")
    client.syscalls.call.return_value = {"status": "success", "data": {"event_id": "e1"}}
    # the REAL aindy-sdk EventAPI (>= 1.0.1) bound to the stubbed syscall transport, so the wire
    # shape asserted below is the SDK's, not a re-statement of it
    client.events = EventAPI(client.syscalls)
    module = types.ModuleType("aindy_sdk")
    module.AINDYClient = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "aindy_sdk", module)
    return client


async def test_emit_event_sends_event_type_on_the_wire(sdk_stub):
    """Through the REAL aindy-sdk `events.emit` (>= 1.0.1), with only the syscall transport
    stubbed: the payload that reaches `syscalls.call` carries `event_type`, the key the runtime's
    `sys.v1.event.emit` requires. Validated against the runtime's own schema below."""
    from claw.aindy.client import _AsyncAINDYClient

    bridge = _AsyncAINDYClient("http://runtime:8000", "aindy_key")
    result = await bridge.emit_event("sys.v1.claw.turn.start", {"agent_id": "a1"})

    sdk_stub.syscalls.call.assert_called_once_with(
        "sys.v1.event.emit",
        {"event_type": "sys.v1.claw.turn.start", "payload": {"agent_id": "a1"}},
    )
    assert result["data"]["event_id"] == "e1"


async def test_emit_event_with_no_payload_sends_an_empty_dict(sdk_stub):
    from claw.aindy.client import _AsyncAINDYClient

    await _AsyncAINDYClient("http://runtime:8000", "k").emit_event("sys.v1.claw.turn.error")
    _, sent = sdk_stub.syscalls.call.call_args.args
    assert sent == {"event_type": "sys.v1.claw.turn.error", "payload": {}}


def test_the_wire_shape_is_what_the_runtime_requires():
    """The other side's schema, not a pin on our own output (the SDK's tests were green for
    months pinning the wrong key). Skips without the runtime installed."""
    pytest.importorskip("AINDY.kernel.syscall_registry")
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY
    from AINDY.kernel.syscall_versioning import validate_payload

    schema = SYSCALL_REGISTRY.get("sys.v1.event.emit").input_schema
    assert validate_payload(schema, {"event_type": "sys.v1.claw.turn.start", "payload": {}}) == []
    assert validate_payload(schema, {"type": "sys.v1.claw.turn.start", "payload": {}}) != []


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
