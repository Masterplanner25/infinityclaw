"""AINDY Phase 10 milestone test -- Session-Persistent Delegation.

Tests (no real server or AINDY needed):
- HandoffRequest.session_key field defaults to ""
- HandoffRequest.session_key can be set to a custom value
- run_agent_turn signature includes session_key parameter
- run_agent_turn appends user message to session when session_key provided (source)
- run_agent_turn appends assistant message to session after turn (source)
- run_agent_turn acquires session lock when session_key provided (source)
- run_agent_turn calls compact_if_needed for session-persistent turns (source)
- _inner_exec in run_agent_turn injects _session_key for coordination tools (source)
- scoped_executor in _run_turn injects _session_key for coordination tools (source)
- delegate_to_agent handler extracts _session_key from injected inputs (source)
- delegate_to_agent derives delegation session key from caller session key (source)
- Delegation key includes from_agent, caller_session, and to_agent (unit)
- AgentDispatcher.dispatch passes session_key to run_agent_turn (source)
- AgentDispatcher docstring updated to reflect Phase 10 (source)
- Session accumulates messages across first persistent call (session manager unit)
- Second call with same session_key receives prior turn in messages list (session manager unit)
- Different session_keys are independent -- no cross-contamination
- run_agent_turn without session_key passes single user message (stateless, backward compat)
- AgentDispatcher.dispatch without session_key still works (stateless backward compat)
- Empty _session_key in tool handler produces empty delegation key (no persistence)

Run:  python tests/test_aindy_phase10.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import traceback
import unittest.mock as mock
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
# 1. HandoffRequest model
# ------------------------------------------------------------------

def test_handoff_request_session_key() -> None:
    print("\n== HandoffRequest.session_key ==")
    try:
        from claw.coordination.model import HandoffRequest

        req = HandoffRequest(from_agent="a", to_agent="b", prompt="hello")
        assert req.session_key == "", f"expected '' got {req.session_key!r}"
        check("HandoffRequest.session_key defaults to empty string", PASS)

        req2 = HandoffRequest(
            from_agent="a", to_agent="b", prompt="hello",
            session_key="delegate:a:sess123:b",
        )
        assert req2.session_key == "delegate:a:sess123:b"
        check("HandoffRequest.session_key can be set to a custom value", PASS)

    except Exception as exc:
        check("HandoffRequest.session_key", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Gateway source inspection — run_agent_turn
# ------------------------------------------------------------------

def test_run_agent_turn_signature() -> None:
    print("\n== run_agent_turn signature ==")
    try:
        import claw.gateway.server as server_mod

        sig = inspect.signature(server_mod.ClawGateway.run_agent_turn)
        params = list(sig.parameters)
        assert "session_key" in params, f"session_key not in params: {params}"
        check("run_agent_turn signature includes session_key parameter", PASS)

        default = sig.parameters["session_key"].default
        assert default == "", f"session_key default should be '' got {default!r}"
        check("run_agent_turn session_key defaults to empty string", PASS)

    except Exception as exc:
        check("run_agent_turn signature", FAIL, str(exc))
        traceback.print_exc()


def test_run_agent_turn_session_wiring() -> None:
    print("\n== run_agent_turn session wiring (source) ==")
    try:
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway.run_agent_turn)

        assert "append_user_message" in src
        check("run_agent_turn calls append_user_message when session_key set", PASS)

        assert "append_assistant_message" in src
        check("run_agent_turn calls append_assistant_message after turn", PASS)

        assert "lock_for" in src
        check("run_agent_turn acquires session lock when session_key set", PASS)

        assert "compact_if_needed" in src
        check("run_agent_turn calls compact_if_needed for session-persistent turns", PASS)

    except Exception as exc:
        check("run_agent_turn session wiring", FAIL, str(exc))
        traceback.print_exc()


def test_inner_exec_injects_session_key() -> None:
    print("\n== _inner_exec injects _session_key ==")
    try:
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway.run_agent_turn)
        assert "_session_key" in src
        check("_inner_exec in run_agent_turn injects _session_key for coordination tools", PASS)

    except Exception as exc:
        check("_inner_exec _session_key injection", FAIL, str(exc))
        traceback.print_exc()


def test_scoped_executor_injects_session_key() -> None:
    print("\n== scoped_executor injects _session_key ==")
    try:
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway._run_turn)
        assert "_session_key" in src
        check("scoped_executor in _run_turn injects _session_key for coordination tools", PASS)

    except Exception as exc:
        check("scoped_executor _session_key injection", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. Delegation tool pipeline (source inspection)
# ------------------------------------------------------------------

def test_delegation_tool_session_key_wiring() -> None:
    print("\n== delegate_to_agent handler session_key wiring (source) ==")
    try:
        import claw.coordination.tools as tools_mod

        src = inspect.getsource(tools_mod.register_delegation_tool)

        assert "_session_key" in src
        check("delegate_to_agent handler extracts _session_key from injected inputs", PASS)

        assert "delegation_key" in src
        check("delegate_to_agent derives delegation session key from _session_key", PASS)

        assert "delegate:" in src
        check("delegation key format uses 'delegate:' prefix", PASS)

        assert "session_key=delegation_key" in src
        check("HandoffRequest constructed with derived delegation_key", PASS)

    except Exception as exc:
        check("delegation tool session_key wiring", FAIL, str(exc))
        traceback.print_exc()


def test_dispatcher_passes_session_key() -> None:
    print("\n== AgentDispatcher passes session_key (source) ==")
    try:
        import claw.coordination.dispatcher as disp_mod

        src = inspect.getsource(disp_mod.AgentDispatcher.dispatch)
        assert "session_key" in src
        check("AgentDispatcher.dispatch passes session_key to run_agent_turn", PASS)

        src_class = inspect.getsource(disp_mod.AgentDispatcher)
        assert "Phase 10" in src_class
        check("AgentDispatcher docstring updated to reference Phase 10", PASS)

    except Exception as exc:
        check("AgentDispatcher session_key wiring", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. Delegation key derivation (unit test on handler logic)
# ------------------------------------------------------------------

def test_delegation_key_derivation() -> None:
    print("\n== Delegation key derivation ==")
    try:
        import claw.coordination.tools as tools_mod
        from claw.tools.registry import ToolRegistry
        from claw.coordination.dispatcher import AgentDispatcher

        captured: list[dict] = []

        async def fake_dispatch(req):
            captured.append({"session_key": req.session_key, "to_agent": req.to_agent})
            from claw.coordination.model import HandoffResult
            return HandoffResult(
                from_agent=req.from_agent, to_agent=req.to_agent,
                prompt=req.prompt, response="ok", success=True,
            )

        registry = ToolRegistry()
        gw = mock.MagicMock()
        dispatcher = AgentDispatcher(gw)
        dispatcher.dispatch = fake_dispatch  # type: ignore[method-assign]
        tools_mod.register_delegation_tool(registry, dispatcher)

        executor = registry.executor()

        # With _session_key present: delegation key should be derived
        asyncio.run(executor("delegate_to_agent", {
            "_agent_id": "planner",
            "_session_key": "chan:peer:planner",
            "agent_id": "researcher",
            "prompt": "Find data",
        }))
        assert len(captured) == 1
        expected_key = "delegate:planner:chan:peer:planner:researcher"
        assert captured[0]["session_key"] == expected_key, (
            f"expected {expected_key!r} got {captured[0]['session_key']!r}"
        )
        check("delegation key format: delegate:{from}:{caller_session}:{to}", PASS)

        # Without _session_key: delegation key should be empty string
        asyncio.run(executor("delegate_to_agent", {
            "_agent_id": "planner",
            "agent_id": "researcher",
            "prompt": "Quick question",
        }))
        assert captured[1]["session_key"] == "", (
            f"expected '' got {captured[1]['session_key']!r}"
        )
        check("empty _session_key produces empty delegation key (stateless fallback)", PASS)

    except Exception as exc:
        check("delegation key derivation", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. Session persistence via ClawSessionManager (unit tests)
# ------------------------------------------------------------------

def test_session_persistence_mechanism() -> None:
    print("\n== Session persistence mechanism ==")
    try:
        from claw.sessions.manager import ClawSessionManager
        from claw.config.schema import SessionConfig

        cfg = SessionConfig()
        mgr = ClawSessionManager(cfg)

        session_key = "delegate:a:s1:b"

        # Simulate first run_agent_turn call with session_key
        mgr.append_user_message(session_key, "First prompt")
        messages_before_turn = mgr.get_messages(session_key)
        assert len(messages_before_turn) == 1
        assert messages_before_turn[0]["role"] == "user"
        check("Session created with user message on first call", PASS)

        # Simulate LLM responding
        mgr.append_assistant_message(session_key, "First response")
        messages_after = mgr.get_messages(session_key)
        assert len(messages_after) == 2
        assert messages_after[1]["role"] == "assistant"
        check("Session has 2 messages (user + assistant) after first turn", PASS)

        # Simulate second run_agent_turn call with same session_key
        mgr.append_user_message(session_key, "Second prompt")
        messages_second_turn = mgr.get_messages(session_key)
        assert len(messages_second_turn) == 3
        assert messages_second_turn[0]["content"] == "First prompt"
        assert messages_second_turn[1]["content"] == "First response"
        assert messages_second_turn[2]["content"] == "Second prompt"
        check("Second call with same session_key receives prior turn in message list", PASS)

    except Exception as exc:
        check("session persistence mechanism", FAIL, str(exc))
        traceback.print_exc()


def test_session_independence() -> None:
    print("\n== Session independence ==")
    try:
        from claw.sessions.manager import ClawSessionManager
        from claw.config.schema import SessionConfig

        cfg = SessionConfig()
        mgr = ClawSessionManager(cfg)

        key_a = "delegate:planner:sess1:researcher"
        key_b = "delegate:planner:sess1:writer"

        mgr.append_user_message(key_a, "Research task")
        mgr.append_assistant_message(key_a, "Research done")
        mgr.append_user_message(key_b, "Write task")

        msgs_a = mgr.get_messages(key_a)
        msgs_b = mgr.get_messages(key_b)

        assert len(msgs_a) == 2
        assert len(msgs_b) == 1
        assert msgs_a[0]["content"] == "Research task"
        assert msgs_b[0]["content"] == "Write task"
        check("Different delegation session_keys are independent (no cross-contamination)", PASS)

    except Exception as exc:
        check("session independence", FAIL, str(exc))
        traceback.print_exc()


def test_lock_per_delegation_session() -> None:
    print("\n== Lock per delegation session ==")
    try:
        from claw.sessions.manager import ClawSessionManager
        from claw.config.schema import SessionConfig

        cfg = SessionConfig()
        mgr = ClawSessionManager(cfg)

        key = "delegate:a:s:b"
        lock = mgr.lock_for(key)
        lock2 = mgr.lock_for(key)
        assert lock is lock2, "Same key should return same lock instance"
        check("lock_for returns same Lock object for same session_key", PASS)

        key2 = "delegate:a:s:c"
        lock3 = mgr.lock_for(key2)
        assert lock3 is not lock, "Different keys should return different locks"
        check("lock_for returns different Lock objects for different session_keys", PASS)

    except Exception as exc:
        check("lock per delegation session", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. Backward compatibility
# ------------------------------------------------------------------

def test_dispatcher_stateless_compat() -> None:
    print("\n== Dispatcher stateless backward compat ==")
    try:
        from claw.coordination.dispatcher import AgentDispatcher
        from claw.coordination.model import HandoffRequest
        from claw.config.schema import AgentConfig

        gw = mock.MagicMock()
        gw.config.agents.agents = [AgentConfig(id="main"), AgentConfig(id="researcher")]

        captured_kwargs: list[dict] = []

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            captured_kwargs.append({"session_key": session_key})
            return "result"

        gw.run_agent_turn = _fake_run

        dispatcher = AgentDispatcher(gw)
        req = HandoffRequest(from_agent="main", to_agent="researcher", prompt="p")
        result = asyncio.run(dispatcher.dispatch(req))

        assert result.success is True
        assert captured_kwargs[0]["session_key"] == ""
        check("dispatch with no session_key passes empty session_key to run_agent_turn", PASS)

    except Exception as exc:
        check("dispatcher stateless backward compat", FAIL, str(exc))
        traceback.print_exc()


def test_dispatcher_persistent_session_propagation() -> None:
    print("\n== Dispatcher persistent session propagation ==")
    try:
        from claw.coordination.dispatcher import AgentDispatcher
        from claw.coordination.model import HandoffRequest
        from claw.config.schema import AgentConfig

        gw = mock.MagicMock()
        gw.config.agents.agents = [AgentConfig(id="main"), AgentConfig(id="researcher")]

        captured_kwargs: list[dict] = []

        async def _fake_run(agent_id, prompt, context="", session_key=""):
            captured_kwargs.append({"session_key": session_key})
            return "result"

        gw.run_agent_turn = _fake_run

        dispatcher = AgentDispatcher(gw)
        session = "delegate:main:caller_sess:researcher"
        req = HandoffRequest(
            from_agent="main", to_agent="researcher", prompt="p",
            session_key=session,
        )
        result = asyncio.run(dispatcher.dispatch(req))

        assert result.success is True
        assert captured_kwargs[0]["session_key"] == session
        check("dispatch passes HandoffRequest.session_key to run_agent_turn", PASS)

    except Exception as exc:
        check("dispatcher persistent session propagation", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    test_handoff_request_session_key()
    test_run_agent_turn_signature()
    test_run_agent_turn_session_wiring()
    test_inner_exec_injects_session_key()
    test_scoped_executor_injects_session_key()
    test_delegation_tool_session_key_wiring()
    test_dispatcher_passes_session_key()
    test_delegation_key_derivation()
    test_session_persistence_mechanism()
    test_session_independence()
    test_lock_per_delegation_session()
    test_dispatcher_stateless_compat()
    test_dispatcher_persistent_session_propagation()

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
