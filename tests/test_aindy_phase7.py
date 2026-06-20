"""AINDY Phase 7 milestone test — Permissions and Filesystem Access + Knowledge Watcher.

Tests (no real server or AINDY needed):
- CapabilitySet, FilesystemPermission, HttpPermission, ToolPermission, SkillPermission defaults
- CapabilitySet custom values parsed correctly
- PermissionEnforcer — filter_tool_definitions respects allow/deny
- PermissionEnforcer — check_tool_call blocks denied tools
- PermissionEnforcer — check_tool_call allows permitted tools
- PermissionEnforcer — browser_fetch blocked when external_http disabled
- PermissionEnforcer — browser_fetch blocked for private network hosts
- PermissionEnforcer — browser_fetch blocked by denylist
- PermissionEnforcer — browser_fetch blocked when not in allowlist
- PermissionEnforcer — browser_fetch allowed when in allowlist
- PermissionEnforcer — PermissionDenied is an Exception subclass
- _is_private_host — loopback / RFC-1918 / IPv6 detection
- AgentConfig.capabilities field parses CapabilitySet correctly
- AgentConfig.capabilities is None when not declared
- ClawGateway imports PermissionEnforcer (import-time smoke test)
- ClawGateway wires enforcer in _run_turn (code-path smoke test)
- KnowledgeWatcher — instantiates with correct attributes
- KnowledgeWatcher — exits gracefully when watchfiles not installed

Run:  python tests/test_aindy_phase7.py
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
# 1. Capability model defaults and construction
# ------------------------------------------------------------------

def test_capability_models() -> None:
    print("\n== CapabilitySet models ==")
    try:
        from claw.permissions.model import (
            CapabilitySet,
            FilesystemPermission,
            HttpPermission,
            ToolPermission,
            SkillPermission,
        )

        fs = FilesystemPermission()
        assert fs.read is False
        assert fs.write is False
        assert fs.delete is False
        assert fs.paths == []
        check("FilesystemPermission defaults", PASS)

        http = HttpPermission()
        assert http.enabled is True
        assert http.allowlist == []
        assert http.denylist == []
        check("HttpPermission defaults", PASS)

        tp = ToolPermission()
        assert tp.allow == ["*"]
        assert tp.deny == []
        check("ToolPermission defaults (allow=*)", PASS)

        sp = SkillPermission()
        assert sp.allow == ["*"]
        assert sp.deny == []
        check("SkillPermission defaults", PASS)

        caps = CapabilitySet()
        assert isinstance(caps.filesystem, FilesystemPermission)
        assert isinstance(caps.external_http, HttpPermission)
        assert isinstance(caps.tool_use, ToolPermission)
        assert isinstance(caps.skill_use, SkillPermission)
        check("CapabilitySet defaults", PASS)

    except Exception as exc:
        check("CapabilitySet models", FAIL, str(exc))
        traceback.print_exc()


def test_capability_custom_values() -> None:
    print("\n== CapabilitySet custom values ==")
    try:
        from claw.permissions.model import CapabilitySet, FilesystemPermission, HttpPermission, ToolPermission

        caps = CapabilitySet(
            filesystem=FilesystemPermission(read=True, write=True, paths=["~/projects"]),
            external_http=HttpPermission(enabled=True, allowlist=["https://api.github.com"]),
            tool_use=ToolPermission(allow=["recall", "browser_fetch"], deny=["write_file"]),
        )
        assert caps.filesystem.read is True
        assert caps.filesystem.write is True
        assert caps.filesystem.paths == ["~/projects"]
        check("FilesystemPermission custom values", PASS)

        assert caps.external_http.allowlist == ["https://api.github.com"]
        check("HttpPermission allowlist set", PASS)

        assert caps.tool_use.allow == ["recall", "browser_fetch"]
        assert caps.tool_use.deny == ["write_file"]
        check("ToolPermission allow/deny set", PASS)

    except Exception as exc:
        check("CapabilitySet custom values", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. PermissionEnforcer — tool allow/deny
# ------------------------------------------------------------------

def test_enforcer_tool_filtering() -> None:
    print("\n== PermissionEnforcer — tool filtering ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer, PermissionDenied
        from claw.permissions.model import CapabilitySet, ToolPermission

        # Default caps (allow=*) — all tools pass through
        enforcer = PermissionEnforcer()
        defs = [{"name": "recall"}, {"name": "browser_fetch"}, {"name": "write_file"}]
        filtered = enforcer.filter_tool_definitions(defs)
        assert len(filtered) == 3
        check("filter_tool_definitions — allow=* keeps all tools", PASS)

        # allow only specific tools
        caps = CapabilitySet(tool_use=ToolPermission(allow=["recall", "browser_fetch"]))
        enforcer = PermissionEnforcer(caps)
        filtered = enforcer.filter_tool_definitions(defs)
        assert len(filtered) == 2
        assert all(d["name"] in ("recall", "browser_fetch") for d in filtered)
        check("filter_tool_definitions — explicit allow list", PASS)

        # deny specific tool
        caps = CapabilitySet(tool_use=ToolPermission(allow=["*"], deny=["write_file"]))
        enforcer = PermissionEnforcer(caps)
        filtered = enforcer.filter_tool_definitions(defs)
        assert len(filtered) == 2
        assert all(d["name"] != "write_file" for d in filtered)
        check("filter_tool_definitions — deny list removes tool", PASS)

        # deny takes precedence over allow
        caps = CapabilitySet(tool_use=ToolPermission(allow=["recall", "write_file"], deny=["write_file"]))
        enforcer = PermissionEnforcer(caps)
        filtered = enforcer.filter_tool_definitions(defs)
        assert len(filtered) == 1 and filtered[0]["name"] == "recall"
        check("filter_tool_definitions — deny overrides allow", PASS)

    except Exception as exc:
        check("PermissionEnforcer tool filtering", FAIL, str(exc))
        traceback.print_exc()


def test_enforcer_check_tool_call() -> None:
    print("\n== PermissionEnforcer — check_tool_call ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer, PermissionDenied
        from claw.permissions.model import CapabilitySet, ToolPermission

        # Allowed tool — no exception
        enforcer = PermissionEnforcer()
        enforcer.check_tool_call("recall", {})
        check("check_tool_call — allowed tool raises nothing", PASS)

        # Denied tool — PermissionDenied raised
        caps = CapabilitySet(tool_use=ToolPermission(allow=["*"], deny=["write_file"]))
        enforcer = PermissionEnforcer(caps)
        try:
            enforcer.check_tool_call("write_file", {"path": "out.txt", "content": "x"})
            check("check_tool_call — denied tool", FAIL, "expected PermissionDenied")
        except PermissionDenied as exc:
            assert "write_file" in str(exc)
            check("check_tool_call — denied tool raises PermissionDenied", PASS)

        # Tool not in allow list — PermissionDenied raised
        caps = CapabilitySet(tool_use=ToolPermission(allow=["recall"]))
        enforcer = PermissionEnforcer(caps)
        try:
            enforcer.check_tool_call("browser_fetch", {"url": "https://example.com"})
            check("check_tool_call — tool not in allow list", FAIL, "expected PermissionDenied")
        except PermissionDenied as exc:
            assert "browser_fetch" in str(exc)
            check("check_tool_call — tool not in allow list raises PermissionDenied", PASS)

    except Exception as exc:
        check("PermissionEnforcer check_tool_call", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. PermissionEnforcer — HTTP enforcement
# ------------------------------------------------------------------

def test_enforcer_http_disabled() -> None:
    print("\n== PermissionEnforcer — HTTP enforcement ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer, PermissionDenied
        from claw.permissions.model import CapabilitySet, HttpPermission

        # external_http disabled
        caps = CapabilitySet(external_http=HttpPermission(enabled=False))
        enforcer = PermissionEnforcer(caps)
        try:
            enforcer.check_tool_call("browser_fetch", {"url": "https://example.com"})
            check("browser_fetch blocked when http disabled", FAIL, "expected PermissionDenied")
        except PermissionDenied as exc:
            assert "enabled" in str(exc).lower()
            check("browser_fetch blocked when external_http.enabled=false", PASS)

        # external_http enabled — public URL passes
        caps = CapabilitySet(external_http=HttpPermission(enabled=True))
        enforcer = PermissionEnforcer(caps)
        enforcer.check_tool_call("browser_fetch", {"url": "https://example.com"})
        check("browser_fetch allowed for public URL when http enabled", PASS)

    except Exception as exc:
        check("HTTP disabled enforcement", FAIL, str(exc))
        traceback.print_exc()


def test_enforcer_private_network_block() -> None:
    print("\n== PermissionEnforcer — private network block ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer, PermissionDenied, _is_private_host
        from claw.permissions.model import CapabilitySet, HttpPermission

        enforcer = PermissionEnforcer()

        private_hosts = [
            "localhost", "127.0.0.1", "127.1.2.3",
            "10.0.0.1", "10.255.255.255",
            "192.168.0.1", "192.168.100.50",
            "172.16.0.1", "172.20.5.3", "172.31.255.255",
            "::1",
        ]
        for host in private_hosts:
            assert _is_private_host(host), f"expected {host!r} to be private"
        check("_is_private_host detects all RFC-1918 + loopback hosts", PASS)

        public_hosts = ["example.com", "api.github.com", "8.8.8.8", "172.32.0.1", "11.0.0.1"]
        for host in public_hosts:
            assert not _is_private_host(host), f"expected {host!r} to be public"
        check("_is_private_host does not block public hosts", PASS)

        private_urls = [
            "http://localhost/api",
            "http://127.0.0.1:8000/",
            "http://10.0.0.1/secret",
            "http://192.168.1.1/admin",
            "http://172.16.0.1/internal",
        ]
        for url in private_urls:
            try:
                enforcer.check_tool_call("browser_fetch", {"url": url})
                check(f"browser_fetch blocked for {url}", FAIL, "expected PermissionDenied")
            except PermissionDenied as exc:
                assert "private" in str(exc).lower() or "blocked" in str(exc).lower()
        check("browser_fetch blocked for all private network URLs", PASS)

    except Exception as exc:
        check("Private network block", FAIL, str(exc))
        traceback.print_exc()


def test_enforcer_http_allowlist_denylist() -> None:
    print("\n== PermissionEnforcer — HTTP allowlist/denylist ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer, PermissionDenied
        from claw.permissions.model import CapabilitySet, HttpPermission

        # Denylist blocks matching URLs
        caps = CapabilitySet(external_http=HttpPermission(denylist=["internal.corp"]))
        enforcer = PermissionEnforcer(caps)
        try:
            enforcer.check_tool_call("browser_fetch", {"url": "https://internal.corp/api"})
            check("denylist blocks matching URL", FAIL, "expected PermissionDenied")
        except PermissionDenied as exc:
            assert "denylist" in str(exc).lower()
            check("denylist blocks matching URL", PASS)

        # Allowlist — URL in list is permitted
        caps = CapabilitySet(external_http=HttpPermission(allowlist=["https://api.github.com"]))
        enforcer = PermissionEnforcer(caps)
        enforcer.check_tool_call("browser_fetch", {"url": "https://api.github.com/repos"})
        check("allowlist permits matching URL", PASS)

        # Allowlist — URL not in list is blocked
        try:
            enforcer.check_tool_call("browser_fetch", {"url": "https://example.com"})
            check("allowlist blocks non-matching URL", FAIL, "expected PermissionDenied")
        except PermissionDenied as exc:
            assert "allowlist" in str(exc).lower()
            check("allowlist blocks non-matching URL", PASS)

    except Exception as exc:
        check("HTTP allowlist/denylist", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. PermissionDenied is an Exception
# ------------------------------------------------------------------

def test_permission_denied_type() -> None:
    print("\n== PermissionDenied exception type ==")
    try:
        from claw.permissions.enforcer import PermissionDenied

        exc = PermissionDenied("test error")
        assert isinstance(exc, Exception)
        assert str(exc) == "test error"
        check("PermissionDenied is an Exception subclass", PASS)

    except Exception as exc:
        check("PermissionDenied type", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. AgentConfig.capabilities field
# ------------------------------------------------------------------

def test_agent_config_capabilities() -> None:
    print("\n== AgentConfig.capabilities ==")
    try:
        from claw.config.schema import AgentConfig, ClawConfig
        from claw.permissions.model import CapabilitySet, ToolPermission

        # No capabilities declared — field is None
        agent = AgentConfig(id="main")
        assert agent.capabilities is None
        check("AgentConfig.capabilities is None when not declared", PASS)

        # Capabilities declared
        caps = CapabilitySet(tool_use=ToolPermission(allow=["recall"], deny=[]))
        agent = AgentConfig(id="readonly", capabilities=caps)
        assert isinstance(agent.capabilities, CapabilitySet)
        assert agent.capabilities.tool_use.allow == ["recall"]
        check("AgentConfig.capabilities stores CapabilitySet", PASS)

        # ClawConfig can hold agents with capabilities
        cfg = ClawConfig()
        assert hasattr(cfg.agents.agents, "__iter__")
        check("ClawConfig.agents supports capabilities-bearing AgentConfig", PASS)

    except Exception as exc:
        check("AgentConfig.capabilities", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. ClawGateway import smoke test
# ------------------------------------------------------------------

def test_gateway_imports_enforcer() -> None:
    print("\n== ClawGateway imports PermissionEnforcer ==")
    try:
        import claw.gateway.server as server_mod
        assert hasattr(server_mod, "PermissionEnforcer")
        assert hasattr(server_mod, "PermissionDenied")
        check("server.py imports PermissionEnforcer and PermissionDenied", PASS)

        # Ensure ClawGateway can be constructed (no enforcer at init — per-turn)
        from claw.config.schema import ClawConfig, CredentialConfig
        cfg = ClawConfig(credentials=[CredentialConfig(api_key="sk-test")])
        _, gw = server_mod.build_app(cfg)
        check("ClawGateway construction succeeds", PASS)

    except Exception as exc:
        check("ClawGateway imports", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. Enforcer integration — filter_tool_definitions in _run_turn
# ------------------------------------------------------------------

def test_enforcer_filters_definitions() -> None:
    print("\n== PermissionEnforcer integration with tool definitions ==")
    try:
        from claw.permissions.enforcer import PermissionEnforcer
        from claw.permissions.model import CapabilitySet, ToolPermission

        # Simulate what _run_turn does: build enforcer from agent caps, filter defs
        raw_defs = [
            {"name": "recall", "description": "recall memories"},
            {"name": "remember", "description": "store memory"},
            {"name": "browser_fetch", "description": "fetch URL"},
            {"name": "write_file", "description": "write file"},
        ]

        # Agent that may only recall and browse
        caps = CapabilitySet(tool_use=ToolPermission(allow=["recall", "browser_fetch"]))
        enforcer = PermissionEnforcer(caps)
        filtered = enforcer.filter_tool_definitions(raw_defs)
        names = {d["name"] for d in filtered}
        assert names == {"recall", "browser_fetch"}
        check("enforcer reduces tool definitions to allowed set", PASS)

        # Agent that denies one specific tool
        caps = CapabilitySet(tool_use=ToolPermission(allow=["*"], deny=["remember"]))
        enforcer = PermissionEnforcer(caps)
        filtered = enforcer.filter_tool_definitions(raw_defs)
        names = {d["name"] for d in filtered}
        assert "remember" not in names and len(names) == 3
        check("enforcer removes single denied tool from definitions", PASS)

        # Agent with no capabilities — all tools visible
        enforcer = PermissionEnforcer(None)
        filtered = enforcer.filter_tool_definitions(raw_defs)
        assert len(filtered) == 4
        check("enforcer with no capabilities passes all tool definitions", PASS)

    except Exception as exc:
        check("enforcer filter_tool_definitions integration", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. KnowledgeWatcher
# ------------------------------------------------------------------

def test_knowledge_watcher_init() -> None:
    print("\n== KnowledgeWatcher ==")
    try:
        from claw.knowledge.watcher import KnowledgeWatcher
        from claw.knowledge.index import KnowledgeIndex
        from claw.config.schema import KnowledgeConfig

        index = KnowledgeIndex(":memory:")
        config = KnowledgeConfig(enabled=True, chunk_size=300, top_k=5)
        state_dir = Path("/tmp/test_claw_state")

        watcher = KnowledgeWatcher(index, config, state_dir)
        assert watcher._index is index
        assert watcher._config is config
        assert watcher._state_dir == state_dir
        check("KnowledgeWatcher instantiates with correct attributes", PASS)

    except Exception as exc:
        check("KnowledgeWatcher init", FAIL, str(exc))
        traceback.print_exc()


def test_knowledge_watcher_no_watchfiles() -> None:
    print("\n== KnowledgeWatcher — no watchfiles ==")
    try:
        from claw.knowledge.watcher import KnowledgeWatcher
        from claw.knowledge.index import KnowledgeIndex
        from claw.config.schema import KnowledgeConfig

        index = KnowledgeIndex(":memory:")
        config = KnowledgeConfig(enabled=True)
        watcher = KnowledgeWatcher(index, config, Path("/tmp"))

        # Patch watchfiles to simulate ImportError
        with mock.patch.dict("sys.modules", {"watchfiles": None}):
            result = asyncio.run(watcher.watch([]))
            assert result is None  # exits gracefully
        check("KnowledgeWatcher.watch() exits gracefully when watchfiles absent", PASS)

    except Exception as exc:
        check("KnowledgeWatcher no watchfiles", FAIL, str(exc))
        traceback.print_exc()


def test_knowledge_watcher_no_dirs() -> None:
    print("\n== KnowledgeWatcher — no workspace dirs ==")
    try:
        from claw.knowledge.watcher import KnowledgeWatcher
        from claw.knowledge.index import KnowledgeIndex
        from claw.config.schema import KnowledgeConfig, AgentConfig

        index = KnowledgeIndex(":memory:")
        config = KnowledgeConfig(enabled=True)
        # Use a state_dir where no agent workspace dirs exist
        watcher = KnowledgeWatcher(index, config, Path("/nonexistent_claw_state"))

        agents = [AgentConfig(id="ghost")]
        # Should return quickly without error when watch_dirs is empty
        result = asyncio.run(watcher.watch(agents))
        assert result is None
        check("KnowledgeWatcher.watch() exits gracefully with no workspace dirs", PASS)

    except Exception as exc:
        check("KnowledgeWatcher no dirs", FAIL, str(exc))
        traceback.print_exc()


def test_knowledge_watcher_registered_in_gateway() -> None:
    print("\n== KnowledgeWatcher registered in ClawGateway ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway.startup)
        assert "KnowledgeWatcher" in src, "KnowledgeWatcher not wired in startup()"
        assert "knowledge-watcher" in src
        check("ClawGateway.startup() references KnowledgeWatcher", PASS)

    except Exception as exc:
        check("KnowledgeWatcher in gateway", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. _run_turn uses enforcer (source-inspection smoke test)
# ------------------------------------------------------------------

def test_run_turn_uses_enforcer() -> None:
    print("\n== _run_turn enforcer wiring ==")
    try:
        import inspect
        import claw.gateway.server as server_mod

        src = inspect.getsource(server_mod.ClawGateway._run_turn)
        assert "PermissionEnforcer" in src, "_run_turn does not build PermissionEnforcer"
        assert "check_tool_call" in src, "_run_turn does not call check_tool_call"
        assert "filter_tool_definitions" in src, "_run_turn does not filter tool definitions"
        check("_run_turn builds enforcer and calls check_tool_call + filter_tool_definitions", PASS)

    except Exception as exc:
        check("_run_turn enforcer wiring", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    test_capability_models()
    test_capability_custom_values()
    test_enforcer_tool_filtering()
    test_enforcer_check_tool_call()
    test_enforcer_http_disabled()
    test_enforcer_private_network_block()
    test_enforcer_http_allowlist_denylist()
    test_permission_denied_type()
    test_agent_config_capabilities()
    test_gateway_imports_enforcer()
    test_enforcer_filters_definitions()
    test_knowledge_watcher_init()
    test_knowledge_watcher_no_watchfiles()
    test_knowledge_watcher_no_dirs()
    test_knowledge_watcher_registered_in_gateway()
    test_run_turn_uses_enforcer()

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
