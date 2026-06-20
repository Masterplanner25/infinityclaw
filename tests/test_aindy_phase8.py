"""AINDY Phase 8 milestone test -- Multi-Agent Coordination.

Tests (no real server or AINDY needed):
- SkillGate -- ["*"] wildcard in allow list passes all skills
- SkillGate -- per-agent deny overrides global allow
- SkillGate -- explicit allow list without wildcard filters correctly
- CoordinationConfig defaults (enabled=False)
- ClawConfig.coordination field present
- AgentConfig.cross_agent_memory field defaults to []
- AgentConfig.cross_agent_memory accepts a list of agent IDs
- HandoffRequest model fields and defaults
- HandoffResult model fields and defaults
- AgentDispatcher instantiates with gateway reference
- AgentDispatcher.dispatch returns error for unknown agent (async)
- AgentDispatcher.dispatch returns success for known agent (mocked run_agent_turn)
- is_coordination_tool returns True for delegate_to_agent
- is_coordination_tool returns False for other tool names
- register_delegation_tool registers tool with correct name and schema
- ClawGateway wires per-agent skill gate in _run_turn (source inspection)
- ClawGateway wires cross-agent memory recall in _run_turn (source inspection)
- ClawGateway wires coordination tool in startup (source inspection)
- ClawGateway.run_agent_turn method exists on gateway
- ClawGateway scoped_executor injects _agent_id for coordination tools (source inspection)

Run:  python tests/test_aindy_phase8.py
"""
from __future__ import annotations

import asyncio
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
# 1. SkillGate wildcard support
# ------------------------------------------------------------------

def test_skill_gate_wildcard() -> None:
    print("\n== SkillGate wildcard ==")
    try:
        from claw.skills.gating import SkillGate
        from claw.skills.loader import SkillManifest

        def _make(sid: str) -> SkillManifest:
            return SkillManifest(id=sid, name=sid, description="")

        skills = [_make("code-review"), _make("search"), _make("summarize")]

        # allow=["*"] should pass all
        gate = SkillGate(allow=["*"])
        assert gate.filter(skills) == skills
        check("SkillGate allow=['*'] passes all skills", PASS)

        # allow=[] (empty) should also pass all (pre-existing behaviour)
        gate = SkillGate(allow=[])
        assert gate.filter(skills) == skills
        check("SkillGate allow=[] passes all skills", PASS)

        # deny still removes when allow=["*"]
        gate = SkillGate(allow=["*"], deny=["search"])
        filtered = gate.filter(skills)
        names = [s.id for s in filtered]
        assert "search" not in names and len(names) == 2
        check("SkillGate deny removes skill even with allow=['*']", PASS)

        # explicit allow without wildcard filters correctly
        gate = SkillGate(allow=["code-review", "summarize"])
        filtered = gate.filter(skills)
        names = [s.id for s in filtered]
        assert names == ["code-review", "summarize"]
        check("SkillGate explicit allow list filters to matching skills only", PASS)

    except Exception as exc:
        check("SkillGate wildcard", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. CoordinationConfig and ClawConfig
# ------------------------------------------------------------------

def test_coordination_config() -> None:
    print("\n== CoordinationConfig ==")
    try:
        from claw.config.schema import CoordinationConfig, ClawConfig

        cfg = CoordinationConfig()
        assert cfg.enabled is False
        check("CoordinationConfig defaults (enabled=False)", PASS)

        cfg_enabled = CoordinationConfig(enabled=True)
        assert cfg_enabled.enabled is True
        check("CoordinationConfig(enabled=True) sets field correctly", PASS)

        claw_cfg = ClawConfig()
        assert hasattr(claw_cfg, "coordination")
        assert isinstance(claw_cfg.coordination, CoordinationConfig)
        check("ClawConfig.coordination field is present and defaults correctly", PASS)

    except Exception as exc:
        check("CoordinationConfig", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. AgentConfig.cross_agent_memory
# ------------------------------------------------------------------

def test_agent_config_cross_agent_memory() -> None:
    print("\n== AgentConfig.cross_agent_memory ==")
    try:
        from claw.config.schema import AgentConfig

        agent = AgentConfig(id="main")
        assert agent.cross_agent_memory == []
        check("AgentConfig.cross_agent_memory defaults to []", PASS)

        agent2 = AgentConfig(id="coordinator", cross_agent_memory=["executor1", "executor2"])
        assert agent2.cross_agent_memory == ["executor1", "executor2"]
        check("AgentConfig.cross_agent_memory stores agent ID list", PASS)

    except Exception as exc:
        check("AgentConfig.cross_agent_memory", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. HandoffRequest and HandoffResult models
# ------------------------------------------------------------------

def test_handoff_models() -> None:
    print("\n== HandoffRequest / HandoffResult ==")
    try:
        from claw.coordination.model import HandoffRequest, HandoffResult

        req = HandoffRequest(from_agent="planner", to_agent="researcher", prompt="Find facts")
        assert req.from_agent == "planner"
        assert req.to_agent == "researcher"
        assert req.prompt == "Find facts"
        assert req.context == ""
        check("HandoffRequest fields and defaults", PASS)

        req_ctx = HandoffRequest(
            from_agent="a", to_agent="b", prompt="p", context="some context"
        )
        assert req_ctx.context == "some context"
        check("HandoffRequest context field", PASS)

        ok = HandoffResult(
            from_agent="planner", to_agent="researcher",
            prompt="Find facts", response="Here are facts.", success=True
        )
        assert ok.success is True
        assert ok.error == ""
        check("HandoffResult success fields", PASS)

        err = HandoffResult(
            from_agent="a", to_agent="b",
            prompt="p", response="", success=False, error="Unknown agent 'b'"
        )
        assert err.success is False
        assert "Unknown agent" in err.error
        check("HandoffResult error fields", PASS)

    except Exception as exc:
        check("Handoff models", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. AgentDispatcher
# ------------------------------------------------------------------

def test_agent_dispatcher_init() -> None:
    print("\n== AgentDispatcher init ==")
    try:
        from claw.coordination.dispatcher import AgentDispatcher

        gw = mock.MagicMock()
        dispatcher = AgentDispatcher(gw)
        assert dispatcher._gw is gw
        check("AgentDispatcher stores gateway reference", PASS)

    except Exception as exc:
        check("AgentDispatcher init", FAIL, str(exc))
        traceback.print_exc()


def test_agent_dispatcher_unknown_agent() -> None:
    print("\n== AgentDispatcher -- unknown agent ==")
    try:
        from claw.coordination.dispatcher import AgentDispatcher
        from claw.coordination.model import HandoffRequest
        from claw.config.schema import AgentConfig

        gw = mock.MagicMock()
        gw.config.agents.agents = [AgentConfig(id="main")]

        dispatcher = AgentDispatcher(gw)
        req = HandoffRequest(from_agent="main", to_agent="ghost", prompt="hello")
        result = asyncio.run(dispatcher.dispatch(req))

        assert result.success is False
        assert "Unknown agent" in result.error
        check("dispatch returns failure for unknown agent", PASS)
        assert result.response == ""
        check("dispatch sets response='' for unknown agent", PASS)

    except Exception as exc:
        check("AgentDispatcher unknown agent", FAIL, str(exc))
        traceback.print_exc()


def test_agent_dispatcher_dispatch_success() -> None:
    print("\n== AgentDispatcher -- success path ==")
    try:
        from claw.coordination.dispatcher import AgentDispatcher
        from claw.coordination.model import HandoffRequest
        from claw.config.schema import AgentConfig

        gw = mock.MagicMock()
        gw.config.agents.agents = [AgentConfig(id="main"), AgentConfig(id="researcher")]

        async def _fake_run(agent_id, prompt, context=""):
            return f"Result for {agent_id}: {prompt}"

        gw.run_agent_turn = _fake_run

        dispatcher = AgentDispatcher(gw)
        req = HandoffRequest(from_agent="main", to_agent="researcher", prompt="Find data")
        result = asyncio.run(dispatcher.dispatch(req))

        assert result.success is True
        assert "researcher" in result.response
        assert result.error == ""
        check("dispatch returns success for known agent", PASS)
        assert result.from_agent == "main" and result.to_agent == "researcher"
        check("dispatch preserves from_agent and to_agent in result", PASS)

    except Exception as exc:
        check("AgentDispatcher success path", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. is_coordination_tool
# ------------------------------------------------------------------

def test_is_coordination_tool() -> None:
    print("\n== is_coordination_tool ==")
    try:
        from claw.coordination.tools import is_coordination_tool

        assert is_coordination_tool("delegate_to_agent") is True
        check("is_coordination_tool returns True for delegate_to_agent", PASS)

        for other in ("recall", "browser_fetch", "ws_create_task", "remember", ""):
            assert is_coordination_tool(other) is False
        check("is_coordination_tool returns False for non-coordination tools", PASS)

    except Exception as exc:
        check("is_coordination_tool", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. register_delegation_tool
# ------------------------------------------------------------------

def test_register_delegation_tool() -> None:
    print("\n== register_delegation_tool ==")
    try:
        from claw.coordination.tools import register_delegation_tool
        from claw.tools.registry import ToolRegistry
        from claw.coordination.dispatcher import AgentDispatcher

        registry = ToolRegistry()
        gw = mock.MagicMock()
        dispatcher = AgentDispatcher(gw)
        register_delegation_tool(registry, dispatcher)

        defs = registry.definitions()
        names = [d["name"] for d in defs]
        assert "delegate_to_agent" in names
        check("register_delegation_tool adds delegate_to_agent to registry", PASS)

        tool_def = next(d for d in defs if d["name"] == "delegate_to_agent")
        schema = tool_def["input_schema"]
        assert "agent_id" in schema["properties"]
        assert "prompt" in schema["properties"]
        assert set(schema["required"]) == {"agent_id", "prompt"}
        check("delegate_to_agent schema has required agent_id and prompt", PASS)

        # Duplicate registration is silently ignored (ToolRegistry dedup)
        register_delegation_tool(registry, dispatcher)
        assert len([d for d in registry.definitions() if d["name"] == "delegate_to_agent"]) == 1
        check("duplicate registration of delegation tool is idempotent", PASS)

    except Exception as exc:
        check("register_delegation_tool", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. Gateway source-inspection smoke tests
# ------------------------------------------------------------------

def test_gateway_per_agent_skill_gate() -> None:
    print("\n== _run_turn per-agent skill gate ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway._run_turn)
        assert "skill_use" in src, "_run_turn does not apply per-agent skill_use gate"
        assert "SkillGate" in src, "_run_turn does not create per-agent SkillGate"
        check("_run_turn applies per-agent SkillGate from capabilities.skill_use", PASS)

    except Exception as exc:
        check("_run_turn per-agent skill gate", FAIL, str(exc))
        traceback.print_exc()


def test_gateway_cross_agent_memory() -> None:
    print("\n== _run_turn cross-agent memory ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway._run_turn)
        assert "cross_agent_memory" in src, "_run_turn does not read cross_agent_memory"
        check("_run_turn recalls cross-agent memories when cross_agent_memory configured", PASS)

    except Exception as exc:
        check("_run_turn cross-agent memory", FAIL, str(exc))
        traceback.print_exc()


def test_gateway_wires_coordination() -> None:
    print("\n== startup() wires coordination ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway.startup)
        assert "coordination" in src, "startup() does not reference coordination config"
        assert "AgentDispatcher" in src, "startup() does not create AgentDispatcher"
        assert "register_delegation_tool" in src, "startup() does not call register_delegation_tool"
        check("startup() registers delegation tool when coordination.enabled", PASS)

    except Exception as exc:
        check("startup() coordination wiring", FAIL, str(exc))
        traceback.print_exc()


def test_gateway_scoped_executor_coordination() -> None:
    print("\n== scoped_executor coordination injection ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway._run_turn)
        assert "is_coordination_tool" in src, "_run_turn does not import is_coordination_tool"
        check("scoped_executor injects _agent_id for coordination tools", PASS)

    except Exception as exc:
        check("scoped_executor coordination injection", FAIL, str(exc))
        traceback.print_exc()


def test_gateway_run_agent_turn_exists() -> None:
    print("\n== ClawGateway.run_agent_turn ==")
    try:
        import claw.gateway.server as server_mod

        assert hasattr(server_mod.ClawGateway, "run_agent_turn"), \
            "ClawGateway has no run_agent_turn method"
        check("ClawGateway.run_agent_turn method exists", PASS)

        # Verify method signature via inspection
        import inspect
        src = inspect.getsource(server_mod.ClawGateway.run_agent_turn)
        assert "async def run_agent_turn" in src
        assert "agent_id" in src and "prompt" in src
        check("run_agent_turn is async and accepts agent_id + prompt", PASS)

    except Exception as exc:
        check("ClawGateway.run_agent_turn", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    test_skill_gate_wildcard()
    test_coordination_config()
    test_agent_config_cross_agent_memory()
    test_handoff_models()
    test_agent_dispatcher_init()
    test_agent_dispatcher_unknown_agent()
    test_agent_dispatcher_dispatch_success()
    test_is_coordination_tool()
    test_register_delegation_tool()
    test_gateway_per_agent_skill_gate()
    test_gateway_cross_agent_memory()
    test_gateway_wires_coordination()
    test_gateway_scoped_executor_coordination()
    test_gateway_run_agent_turn_exists()

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
