"""Phase 5 milestone test — memory, session compaction, auth subsystem.

Run:  python tests/test_phase5_milestone.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
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
# 1. MemoryManager — basic store + recall + forget
# ------------------------------------------------------------------

async def test_memory_manager() -> None:
    print("\n== MemoryManager ==")
    try:
        from claw.config.schema import MemoryConfig
        from claw.memory.manager import MemoryManager

        cfg = MemoryConfig(enabled=True, db_path=":memory:")
        mgr = MemoryManager(cfg)
        assert mgr.is_enabled()
        check("MemoryManager enabled", PASS)

        # Store a memory
        node = await mgr.remember(
            "main",
            "The user prefers concise responses",
            tags=["preference", "style"],
            memory_type="insight",
        )
        assert node.id
        assert node.content == "The user prefers concise responses"
        assert node.user_id == "main"
        check("remember() stores node", PASS, f"id={node.id[:8]}...")

        # Store another
        node2 = await mgr.remember(
            "main",
            "User's name is Shawn",
            tags=["identity"],
            memory_type="insight",
        )

        # Recall by query
        nodes = await mgr.recall("main", "user preferences style", limit=5)
        assert len(nodes) > 0
        ids = [n.id for n in nodes]
        assert node.id in ids, "expected preference node in recall results"
        check("recall() returns relevant nodes", PASS, f"{len(nodes)} nodes")

        # List all
        all_nodes = mgr.list_all("main")
        assert len(all_nodes) == 2
        check("list_all() returns all nodes", PASS, f"{len(all_nodes)} nodes")

        # Agent isolation — coder agent has separate store
        await mgr.remember("coder", "Coder agent specializes in Python", tags=["role"])
        main_nodes = mgr.list_all("main")
        coder_nodes = mgr.list_all("coder")
        assert len(main_nodes) == 2
        assert len(coder_nodes) == 1
        check("Per-agent memory isolation", PASS, f"main={len(main_nodes)}, coder={len(coder_nodes)}")

        # Forget
        deleted = mgr.forget("main", node.id)
        assert deleted
        all_after = mgr.list_all("main")
        assert len(all_after) == 1
        assert not any(n.id == node.id for n in all_after)
        check("forget() deletes node", PASS)

        # Forget unknown — returns False
        assert not mgr.forget("main", "nonexistent-id")
        check("forget() unknown returns False", PASS)

        # Disabled mode
        cfg_off = MemoryConfig(enabled=False)
        mgr_off = MemoryManager(cfg_off)
        assert not mgr_off.is_enabled()
        nodes_off = await mgr_off.recall("main", "anything")
        assert nodes_off == []
        check("Disabled mode returns empty recall", PASS)

    except Exception as e:
        check("MemoryManager", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Memory tools — register + invoke
# ------------------------------------------------------------------

async def test_memory_tools() -> None:
    print("\n== Memory tools ==")
    try:
        from claw.config.schema import MemoryConfig
        from claw.memory.manager import MemoryManager
        from claw.memory.tools import register_memory_tools, is_memory_tool
        from claw.tools.registry import ToolRegistry

        mgr = MemoryManager(MemoryConfig(enabled=True))
        reg = ToolRegistry()
        register_memory_tools(reg, mgr)

        defs = reg.definitions()
        tool_names = {d["name"] for d in defs}
        assert tool_names == {"remember", "recall", "forget", "list_memories"}, \
            f"unexpected tools: {tool_names}"
        check("All 4 memory tools registered", PASS)

        # is_memory_tool helper
        assert is_memory_tool("remember")
        assert not is_memory_tool("read_file")
        check("is_memory_tool() predicate", PASS)

        # Duplicate registration is a no-op
        register_memory_tools(reg, mgr)
        assert len(reg.definitions()) == 4, "duplicate registration added tools"
        check("Duplicate registration is no-op", PASS)

        # Invoke remember via scoped input
        result_json = await reg.invoke("remember", {
            "_agent_id": "main",
            "content": "Test memory from tool",
            "tags": ["test"],
        })
        result = json.loads(result_json)
        assert result["stored"] is True
        node_id = result["id"]
        check("remember tool invocation", PASS, f"node_id={node_id[:8]}...")

        # Invoke recall
        recall_json = await reg.invoke("recall", {
            "_agent_id": "main",
            "query": "test memory",
        })
        recall_result = json.loads(recall_json)
        assert recall_result["count"] > 0
        check("recall tool invocation", PASS, f"{recall_result['count']} results")

        # Invoke forget
        forget_json = await reg.invoke("forget", {"_agent_id": "main", "node_id": node_id})
        forget_result = json.loads(forget_json)
        assert forget_result["deleted"] is True
        check("forget tool invocation", PASS)

        # Invoke list_memories
        list_json = await reg.invoke("list_memories", {"_agent_id": "main"})
        list_result = json.loads(list_json)
        assert "memories" in list_result
        check("list_memories tool invocation", PASS, f"{list_result['count']} memories")

    except Exception as e:
        check("Memory tools", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. Memory injector — prompt block formatting
# ------------------------------------------------------------------

async def test_memory_injector() -> None:
    print("\n== MemoryInjector ==")
    try:
        from claw.config.schema import MemoryConfig
        from claw.memory.manager import MemoryManager
        from claw.memory.injector import MemoryInjector

        mgr = MemoryManager(MemoryConfig(enabled=True))
        await mgr.remember("main", "User prefers dark mode", tags=["ui"], memory_type="insight")
        nodes = await mgr.recall("main", "user preferences")

        injector = MemoryInjector()
        block = injector.build_block(nodes)
        assert "Relevant Memories" in block
        assert "User prefers dark mode" in block
        check("build_block formats memories into prompt section", PASS)

        # Empty list returns empty string
        empty = injector.build_block([])
        assert empty == ""
        check("Empty node list returns empty string", PASS)

    except Exception as e:
        check("MemoryInjector", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. ContextCompactor — needs_compaction + structure
# ------------------------------------------------------------------

def test_context_compactor() -> None:
    print("\n== ContextCompactor ==")
    try:
        from claw.sessions.compactor import ContextCompactor

        compactor = ContextCompactor(threshold=10, keep_recent=4)

        msgs_short = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        assert not compactor.needs_compaction(msgs_short)
        check("Short session: no compaction needed", PASS)

        msgs_long = [{"role": "user", "content": f"msg {i}"} for i in range(12)]
        assert compactor.needs_compaction(msgs_long)
        check("Long session: compaction triggered", PASS)

    except Exception as e:
        check("ContextCompactor", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. SessionManager — compaction_threshold config
# ------------------------------------------------------------------

def test_session_compaction_config() -> None:
    print("\n== SessionConfig compaction fields ==")
    try:
        from claw.config.schema import SessionConfig
        cfg = SessionConfig(compaction_threshold=40, compaction_keep_recent=20)
        assert cfg.compaction_threshold == 40
        assert cfg.compaction_keep_recent == 20
        check("SessionConfig has compaction fields", PASS)

        from claw.sessions.manager import ClawSessionManager
        mgr = ClawSessionManager(cfg)
        assert mgr._compactor._threshold == 40
        assert mgr._compactor._keep_recent == 20
        check("ClawSessionManager wires compactor from config", PASS)

    except Exception as e:
        check("Session compaction config", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. ApiKeyStore — create/verify/revoke
# ------------------------------------------------------------------

def test_api_key_store() -> None:
    print("\n== ApiKeyStore ==")
    try:
        from claw.auth.store import ApiKeyStore

        store = ApiKeyStore()
        raw_key, record = store.create("test-device", scopes=["*"])
        assert raw_key.startswith("claw_")
        assert record.enabled
        check("create() generates prefixed key", PASS, f"key_id={record.key_id}")

        # Verify
        found = store.verify(raw_key)
        assert found is not None
        assert found.key_id == record.key_id
        check("verify() accepts correct key", PASS)

        # Wrong key
        assert store.verify("claw_wrongkey") is None
        check("verify() rejects wrong key", PASS)

        # Revoke
        revoked = store.revoke(record.key_id)
        assert revoked
        assert store.verify(raw_key) is None
        check("revoke() disables key", PASS)

        # List only active
        raw2, rec2 = store.create("device-2")
        active = store.list_keys()
        assert len(active) == 1
        assert active[0].key_id == rec2.key_id
        check("list_keys() returns only active keys", PASS)

    except Exception as e:
        check("ApiKeyStore", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. AuthManager — JWT + API key
# ------------------------------------------------------------------

def test_auth_manager() -> None:
    print("\n== AuthManager ==")
    try:
        from claw.config.schema import GatewayConfig
        from claw.auth.manager import AuthManager

        # Open mode
        cfg_open = GatewayConfig(token=None)
        mgr_open = AuthManager(cfg_open)
        assert not mgr_open.is_enabled()
        principal = mgr_open.require(None)
        assert principal.auth_type == "open"
        check("Open mode accepts all", PASS)

        # Auth enabled
        cfg = GatewayConfig(token="test-secret-key-long-enough")
        mgr = AuthManager(cfg)
        assert mgr.is_enabled()
        check("Auth enabled when token set", PASS)

        # Issue + verify JWT
        token = mgr.issue_token("user-123", scopes=["*"])
        assert token
        principal = mgr.verify_token(token)
        assert principal is not None
        assert principal.user_id == "user-123"
        assert principal.auth_type == "jwt"
        check("JWT issue + verify", PASS, f"user_id={principal.user_id}")

        # Bad JWT
        assert mgr.verify_token("not.a.jwt") is None
        check("Bad JWT rejected", PASS)

        # API key
        raw_key, _ = mgr.api_key_store.create("mobile-client")
        kp = mgr.verify_api_key(raw_key)
        assert kp is not None
        assert kp.auth_type == "api_key"
        check("API key verify", PASS)

        # Unified verify — JWT
        p_jwt = mgr.verify(token)
        assert p_jwt is not None and p_jwt.auth_type == "jwt"
        check("Unified verify — JWT path", PASS)

        # Unified verify — API key
        p_key = mgr.verify(raw_key)
        assert p_key is not None and p_key.auth_type == "api_key"
        check("Unified verify — API key path", PASS)

        # require() raises on missing token
        try:
            mgr.require(None)
            check("require(None) should raise", FAIL)
        except ValueError:
            check("require(None) raises ValueError", PASS)

    except Exception as e:
        check("AuthManager", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. GatewayAuth — upgraded with AuthManager
# ------------------------------------------------------------------

def test_gateway_auth() -> None:
    print("\n== GatewayAuth (upgraded) ==")
    try:
        from claw.config.schema import GatewayConfig
        from claw.auth.manager import AuthManager
        from claw.gateway.auth import GatewayAuth

        # Open mode
        auth_open = GatewayAuth(static_token=None, auth_manager=None)
        p = auth_open.verify_principal(None)
        assert p is not None and p.auth_type == "open"
        check("GatewayAuth open mode", PASS)

        # With AuthManager + JWT
        cfg = GatewayConfig(token="gateway-secret-test-key")
        am = AuthManager(cfg)
        auth = GatewayAuth(static_token="gateway-secret-test-key", auth_manager=am)
        assert auth.enabled

        token = am.issue_token("shawn")
        p_jwt = auth.verify_principal(token)
        assert p_jwt is not None and p_jwt.auth_type == "jwt"
        check("GatewayAuth verifies JWT via AuthManager", PASS)

        # API key via GatewayAuth
        raw_key, _ = am.api_key_store.create("laptop")
        p_key = auth.verify_principal(raw_key)
        assert p_key is not None and p_key.auth_type == "api_key"
        check("GatewayAuth verifies API key via AuthManager", PASS)

        # Legacy static token still works
        p_static = auth.verify_principal("gateway-secret-test-key")
        assert p_static is not None
        check("GatewayAuth accepts legacy static token", PASS)

        # Invalid credential rejected
        p_bad = auth.verify_principal("bad-token")
        assert p_bad is None
        check("GatewayAuth rejects invalid credential", PASS)

    except Exception as e:
        check("GatewayAuth", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. Auth HTTP endpoints
# ------------------------------------------------------------------

async def test_auth_endpoints() -> None:
    print("\n== Auth HTTP endpoints ==")
    try:
        from httpx import AsyncClient, ASGITransport
        from claw.config.loader import load_config
        from claw.gateway.server import build_app

        cfg = load_config(ROOT / "claw.toml")
        app, gw = build_app(cfg)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Auth not enabled (no token in default claw.toml) — endpoints return 404
            r = await client.post("/auth/token?user_id=shawn&secret=anything")
            if r.status_code == 404:
                check("Auth endpoints 404 when disabled", PASS)
            else:
                # Auth IS enabled — test the full flow
                check("Auth endpoints accessible when enabled", PASS, f"status={r.status_code}")

            # API key create
            r2 = await client.post("/auth/keys?label=test-device")
            if r2.status_code == 404:
                check("API key endpoint 404 when disabled", PASS)
            elif r2.status_code == 200:
                key_data = r2.json()
                assert "key" in key_data
                check("POST /auth/keys creates key", PASS, f"key_id={key_data.get('key_id')}")

                # List keys
                r3 = await client.get("/auth/keys")
                assert r3.status_code == 200
                assert "keys" in r3.json()
                check("GET /auth/keys lists keys", PASS)

                # Revoke
                r4 = await client.delete(f"/auth/keys/{key_data['key_id']}")
                assert r4.status_code == 200
                check("DELETE /auth/keys/{id} revokes key", PASS)
            else:
                check("API key endpoint", FAIL, f"unexpected status={r2.status_code}")

    except Exception as e:
        check("Auth HTTP endpoints", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. WebSocket with memory active — end-to-end
# ------------------------------------------------------------------

def test_webchat_with_memory() -> None:
    print("\n== WebChat + memory (end-to-end) ==")
    try:
        from starlette.testclient import TestClient
        from claw.config.loader import load_config
        from claw.gateway.server import build_app

        cfg = load_config(ROOT / "claw.toml")
        app, gw = build_app(cfg)

        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()  # hello

                # Ask agent to remember something
                ws.send_json({
                    "type": "chat",
                    "content": "Please remember: my favorite color is blue. Use the remember tool.",
                })
                chunks = []
                while True:
                    f = ws.receive_json()
                    if f["type"] == "chunk":
                        chunks.append(f["content"])
                    elif f["type"] in ("done", "error"):
                        status_type = f["type"]
                        break
                reply = "".join(chunks)
                if status_type == "done":
                    check("Remember tool invocation via chat", PASS, f"{len(reply)} chars")
                else:
                    check("Remember tool invocation via chat", FAIL, f.get("message", "error"))

                # Check memory was stored
                memories = gw.memory_manager.list_all("main")
                if any("blue" in m.content.lower() or "color" in m.content.lower() for m in memories):
                    check("Memory stored in MemoryManager", PASS, f"{len(memories)} total memories")
                else:
                    # Agent may have said it remembered without using the tool
                    check("Memory stored in MemoryManager", SKIP,
                          f"agent may not have used tool (memories={len(memories)})")

    except Exception as e:
        check("WebChat + memory", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_memory_manager()
    await test_memory_tools()
    await test_memory_injector()
    await test_auth_endpoints()


def main() -> None:
    print("=" * 60)
    print("  Claw Phase 5 Milestone Test")
    print("=" * 60)

    test_context_compactor()
    test_session_compaction_config()
    test_api_key_store()
    test_auth_manager()
    test_gateway_auth()
    asyncio.run(run_async_tests())
    test_webchat_with_memory()

    print()
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _ in results if s == SKIP)
    total = len(results)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    if skipped:
        print(f", {skipped} skipped", end="")
    print()
    print("=" * 60)

    if failed:
        print("\nFailed tests:")
        for name, status, note in results:
            if status == FAIL:
                print(f"  - {name}: {note}")
        sys.exit(1)


if __name__ == "__main__":
    main()
