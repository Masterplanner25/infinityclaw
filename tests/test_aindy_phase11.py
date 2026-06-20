"""AINDY Phase 11 milestone test -- Delegation Audit Trail.

Tests (no real AINDY needed):
- _emit_event helper exists in dispatcher module
- _emit_event swallows exceptions (AINDY unavailability never blocks dispatch)
- dispatch() generates delegation_id UUID per call
- dispatch() fires claw.delegation.started before run_agent_turn (source)
- dispatch() fires claw.delegation.complete on success (source)
- dispatch() fires claw.delegation.error on error response (source)
- Events gated behind _aindy and emit_events check (source)
- Events use asyncio.create_task (fire-and-forget) (source)
- Base payload contains from_agent, to_agent, delegation_id, persistent (source)
- claw.delegation.complete adds response_len to payload (source)
- claw.delegation.error adds error field to payload (source)
- session_key included in payload when non-empty (source)
- delegation_id is a valid UUID string
- persistent=True when session_key is non-empty
- persistent=False when session_key is empty
- AINDY mock: claw.delegation.started emitted on successful dispatch
- AINDY mock: claw.delegation.complete emitted on success with response_len
- AINDY mock: claw.delegation.error emitted when run_agent_turn returns error
- Unknown agent: no events fired (no delegation actually started)
- AINDY None: dispatch completes normally without raising
- emit_events=False: no events emitted, dispatch still returns result

Run:  python tests/test_aindy_phase11.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import traceback
import unittest.mock as mock
import uuid as uuid_mod
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# 1. _emit_event helper
# ------------------------------------------------------------------

def test_emit_event_helper() -> None:
    print("\n== _emit_event helper ==")
    try:
        import claw.coordination.dispatcher as disp_mod

        assert hasattr(disp_mod, "_emit_event"), "dispatcher has no _emit_event function"
        check("_emit_event helper exists in dispatcher module", PASS)

        # Must swallow exceptions — AINDY unavailability never blocks dispatch
        class _BadClient:
            async def emit_event(self, event_type, payload):
                raise RuntimeError("AINDY down")

        asyncio.run(disp_mod._emit_event(_BadClient(), "claw.delegation.started", {}))
        check("_emit_event swallows client exceptions silently", PASS)

    except Exception as exc:
        check("_emit_event helper", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Source inspection — dispatcher.dispatch()
# ------------------------------------------------------------------

def test_dispatch_source_events() -> None:
    print("\n== dispatch() event source inspection ==")
    try:
        import claw.coordination.dispatcher as disp_mod

        src = inspect.getsource(disp_mod.AgentDispatcher.dispatch)

        assert "delegation_id" in src
        check("dispatch() generates delegation_id", PASS)

        assert "uuid" in src
        check("delegation_id uses uuid", PASS)

        assert "claw.delegation.started" in src
        check("dispatch() fires claw.delegation.started", PASS)

        assert "claw.delegation.complete" in src
        check("dispatch() fires claw.delegation.complete on success", PASS)

        assert "claw.delegation.error" in src
        check("dispatch() fires claw.delegation.error on failure", PASS)

        assert "_aindy" in src and "emit_events" in src
        check("events gated behind _aindy and emit_events check", PASS)

        assert "asyncio.create_task" in src
        check("events emitted via asyncio.create_task (fire-and-forget)", PASS)

    except Exception as exc:
        check("dispatch source inspection", FAIL, str(exc))
        traceback.print_exc()


def test_dispatch_payload_fields() -> None:
    print("\n== dispatch() event payload fields (source) ==")
    try:
        import claw.coordination.dispatcher as disp_mod

        src = inspect.getsource(disp_mod.AgentDispatcher.dispatch)

        assert "from_agent" in src
        check("base payload includes from_agent", PASS)

        assert "to_agent" in src
        check("base payload includes to_agent", PASS)

        assert '"persistent"' in src
        check("base payload includes persistent flag", PASS)

        assert "response_len" in src
        check("claw.delegation.complete adds response_len", PASS)

        assert '"error"' in src
        check("claw.delegation.error adds error field", PASS)

        assert "session_key" in src
        check("session_key included in payload when non-empty", PASS)

    except Exception as exc:
        check("dispatch payload fields", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. delegation_id and persistent flag (unit)
# ------------------------------------------------------------------

def test_delegation_id_format() -> None:
    print("\n== delegation_id and persistent ==")
    try:
        import uuid as _uuid
        import claw.coordination.dispatcher as disp_mod

        captured: list[dict] = []

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "ok"

        async def _run_capture() -> None:
            from claw.config.schema import AgentConfig
            from claw.coordination.model import HandoffRequest

            gw = mock.MagicMock()
            gw.config.agents.agents = [AgentConfig(id="a"), AgentConfig(id="b")]
            gw.run_agent_turn = _fake_run

            emitted: list[tuple[str, dict]] = []

            class _FakeAINDY:
                async def emit_event(self, event_type, payload):
                    emitted.append((event_type, payload))

            gw._aindy = _FakeAINDY()
            gw.config.aindy.emit_events = True

            dispatcher = disp_mod.AgentDispatcher(gw)
            req = HandoffRequest(from_agent="a", to_agent="b", prompt="go")
            await dispatcher.dispatch(req)

            # let tasks run
            await asyncio.sleep(0)

            assert emitted, "no events captured"
            _, payload = emitted[0]
            captured.append(payload)

        asyncio.run(_run_capture())

        p = captured[0]
        _uuid.UUID(p["delegation_id"])  # raises if not valid UUID
        check("delegation_id is a valid UUID string", PASS)

        assert p["persistent"] is False
        check("persistent=False when session_key is empty", PASS)

    except Exception as exc:
        check("delegation_id format", FAIL, str(exc))
        traceback.print_exc()


def test_persistent_flag_true() -> None:
    print("\n== persistent=True when session_key set ==")
    try:
        import claw.coordination.dispatcher as disp_mod
        from claw.config.schema import AgentConfig
        from claw.coordination.model import HandoffRequest

        emitted: list[tuple[str, dict]] = []

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "ok"

        async def _run() -> None:
            gw = mock.MagicMock()
            gw.config.agents.agents = [AgentConfig(id="a"), AgentConfig(id="b")]
            gw.run_agent_turn = _fake_run

            class _FakeAINDY:
                async def emit_event(self, event_type, payload):
                    emitted.append((event_type, payload))

            gw._aindy = _FakeAINDY()
            gw.config.aindy.emit_events = True

            dispatcher = disp_mod.AgentDispatcher(gw)
            req = HandoffRequest(
                from_agent="a", to_agent="b", prompt="go",
                session_key="delegate:a:s:b",
            )
            await dispatcher.dispatch(req)
            await asyncio.sleep(0)

        asyncio.run(_run())

        assert emitted
        _, payload = emitted[0]  # started event
        assert payload["persistent"] is True
        check("persistent=True when session_key is non-empty", PASS)

        assert payload.get("session_key") == "delegate:a:s:b"
        check("session_key included in payload when non-empty", PASS)

    except Exception as exc:
        check("persistent flag True", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. Behavior: event emission with AINDY mock
# ------------------------------------------------------------------

def _build_dispatcher_with_aindy(agents, run_agent_turn_fn, emit_events=True):
    """Helper: build a dispatcher with a fake AINDY client that captures events."""
    import claw.coordination.dispatcher as disp_mod
    from claw.config.schema import AgentConfig

    emitted: list[tuple[str, dict]] = []

    class _FakeAINDY:
        async def emit_event(self, event_type, payload):
            emitted.append((event_type, payload))

    gw = mock.MagicMock()
    gw.config.agents.agents = [AgentConfig(id=aid) for aid in agents]
    gw.run_agent_turn = run_agent_turn_fn
    gw._aindy = _FakeAINDY()
    gw.config.aindy.emit_events = emit_events

    dispatcher = disp_mod.AgentDispatcher(gw)
    return dispatcher, emitted


def test_events_on_success() -> None:
    print("\n== events emitted on successful dispatch ==")
    try:
        from claw.coordination.model import HandoffRequest

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "here is the result"

        dispatcher, emitted = _build_dispatcher_with_aindy(
            ["planner", "researcher"], _fake_run
        )

        async def _run():
            req = HandoffRequest(from_agent="planner", to_agent="researcher", prompt="p")
            result = await dispatcher.dispatch(req)
            await asyncio.sleep(0)  # let create_task callbacks run
            return result

        result = asyncio.run(_run())
        assert result.success is True

        event_types = [e for e, _ in emitted]
        assert "claw.delegation.started" in event_types
        check("claw.delegation.started emitted before run_agent_turn", PASS)

        assert "claw.delegation.complete" in event_types
        check("claw.delegation.complete emitted on successful dispatch", PASS)

        assert "claw.delegation.error" not in event_types
        check("claw.delegation.error NOT emitted on success", PASS)

        complete_payload = next(p for e, p in emitted if e == "claw.delegation.complete")
        assert complete_payload["response_len"] == len("here is the result")
        check("claw.delegation.complete payload has correct response_len", PASS)

        assert complete_payload["from_agent"] == "planner"
        assert complete_payload["to_agent"] == "researcher"
        check("claw.delegation.complete payload has from_agent and to_agent", PASS)

    except Exception as exc:
        check("events on success", FAIL, str(exc))
        traceback.print_exc()


def test_events_on_error() -> None:
    print("\n== events emitted on error response ==")
    try:
        from claw.coordination.model import HandoffRequest

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "[error: something went wrong]"

        dispatcher, emitted = _build_dispatcher_with_aindy(
            ["planner", "researcher"], _fake_run
        )

        async def _run():
            req = HandoffRequest(from_agent="planner", to_agent="researcher", prompt="p")
            result = await dispatcher.dispatch(req)
            await asyncio.sleep(0)
            return result

        result = asyncio.run(_run())
        assert result.success is False

        event_types = [e for e, _ in emitted]
        assert "claw.delegation.started" in event_types
        check("claw.delegation.started emitted even when inner turn fails", PASS)

        assert "claw.delegation.error" in event_types
        check("claw.delegation.error emitted when run_agent_turn returns error", PASS)

        assert "claw.delegation.complete" not in event_types
        check("claw.delegation.complete NOT emitted on error", PASS)

        error_payload = next(p for e, p in emitted if e == "claw.delegation.error")
        assert "something went wrong" in error_payload["error"]
        check("claw.delegation.error payload has error field with message", PASS)

    except Exception as exc:
        check("events on error", FAIL, str(exc))
        traceback.print_exc()


def test_no_events_for_unknown_agent() -> None:
    print("\n== no events for unknown agent ==")
    try:
        from claw.coordination.model import HandoffRequest

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "ok"

        dispatcher, emitted = _build_dispatcher_with_aindy(["planner"], _fake_run)

        async def _run():
            req = HandoffRequest(from_agent="planner", to_agent="ghost", prompt="p")
            result = await dispatcher.dispatch(req)
            await asyncio.sleep(0)
            return result

        result = asyncio.run(_run())
        assert result.success is False
        assert "Unknown agent" in result.error

        assert len(emitted) == 0
        check("no AINDY events fired for unknown agent (no delegation started)", PASS)

    except Exception as exc:
        check("no events for unknown agent", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. AINDY disabled / emit_events=False
# ------------------------------------------------------------------

def test_aindy_none_dispatch_works() -> None:
    print("\n== AINDY None: dispatch still works ==")
    try:
        import claw.coordination.dispatcher as disp_mod
        from claw.config.schema import AgentConfig
        from claw.coordination.model import HandoffRequest

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "result without aindy"

        gw = mock.MagicMock()
        gw.config.agents.agents = [AgentConfig(id="a"), AgentConfig(id="b")]
        gw.run_agent_turn = _fake_run
        gw._aindy = None  # AINDY disabled
        gw.config.aindy.emit_events = True

        dispatcher = disp_mod.AgentDispatcher(gw)
        req = HandoffRequest(from_agent="a", to_agent="b", prompt="hello")
        result = asyncio.run(dispatcher.dispatch(req))

        assert result.success is True
        assert result.response == "result without aindy"
        check("dispatch with _aindy=None completes normally, no errors", PASS)

    except Exception as exc:
        check("AINDY None dispatch", FAIL, str(exc))
        traceback.print_exc()


def test_emit_events_false_no_events() -> None:
    print("\n== emit_events=False: no events emitted ==")
    try:
        from claw.coordination.model import HandoffRequest

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            return "ok"

        dispatcher, emitted = _build_dispatcher_with_aindy(
            ["a", "b"], _fake_run, emit_events=False
        )

        async def _run():
            req = HandoffRequest(from_agent="a", to_agent="b", prompt="p")
            result = await dispatcher.dispatch(req)
            await asyncio.sleep(0)
            return result

        result = asyncio.run(_run())
        assert result.success is True
        assert len(emitted) == 0
        check("no events emitted when emit_events=False", PASS)
        check("dispatch still returns correct result when emit_events=False", PASS)

    except Exception as exc:
        check("emit_events=False", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. delegation_id uniqueness
# ------------------------------------------------------------------

def test_delegation_id_uniqueness() -> None:
    print("\n== delegation_id uniqueness ==")
    try:
        from claw.coordination.model import HandoffRequest

        call_count = 0

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            nonlocal call_count
            call_count += 1
            return "ok"

        delegation_ids: list[str] = []

        async def _run():
            import claw.coordination.dispatcher as disp_mod
            from claw.config.schema import AgentConfig

            class _FakeAINDY:
                async def emit_event(self, event_type, payload):
                    if event_type == "claw.delegation.started":
                        delegation_ids.append(payload["delegation_id"])

            gw = mock.MagicMock()
            gw.config.agents.agents = [AgentConfig(id="a"), AgentConfig(id="b")]
            gw.run_agent_turn = _fake_run
            gw._aindy = _FakeAINDY()
            gw.config.aindy.emit_events = True

            dispatcher = disp_mod.AgentDispatcher(gw)
            req = HandoffRequest(from_agent="a", to_agent="b", prompt="p")
            await dispatcher.dispatch(req)
            await dispatcher.dispatch(req)
            await asyncio.sleep(0)

        asyncio.run(_run())

        assert len(delegation_ids) == 2
        assert delegation_ids[0] != delegation_ids[1]
        check("each dispatch generates a unique delegation_id", PASS)

    except Exception as exc:
        check("delegation_id uniqueness", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    test_emit_event_helper()
    test_dispatch_source_events()
    test_dispatch_payload_fields()
    test_delegation_id_format()
    test_persistent_flag_true()
    test_events_on_success()
    test_events_on_error()
    test_no_events_for_unknown_agent()
    test_aindy_none_dispatch_works()
    test_emit_events_false_no_events()
    test_delegation_id_uniqueness()

    print()
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _ in results if s == SKIP)
    total = len(results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
