"""AINDY Phase 2 milestone test — memory backend delegation.

Tests MemoryManager with a mock _AsyncAINDYClient so no real AINDY server is needed.
Verifies: remember/recall/list_all/get/forget all route through AINDY; aindy-fallback
mode falls back to SQLite on AINDY error; local mode never calls AINDY.

Run:  python tests/test_aindy_phase2.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from nodus_memory import MemoryNode

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# Mock AINDY client
# ------------------------------------------------------------------

class _MockAINDYClient:
    """In-memory stand-in for _AsyncAINDYClient — no network required."""

    def __init__(self, fail: bool = False) -> None:
        self._store: dict[str, str] = {}  # path -> JSON content
        self._events: list[dict] = []
        self.fail = fail  # if True, all memory ops raise

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("mock AINDY unavailable")

    async def emit_event(self, event_type: str, payload: dict | None = None) -> dict:
        self._events.append({"type": event_type, "payload": payload})
        return {"ok": True}

    async def memory_write(self, path: str, content: str, **_: Any) -> dict:
        self._check()
        self._store[path] = content
        return {"ok": True, "path": path}

    async def memory_read(self, path: str, **_: Any) -> dict:
        self._check()
        content = self._store.get(path)
        if content is None:
            raise KeyError(f"not found: {path}")
        return {"content": content}

    async def memory_search(self, query: str, **kwargs: Any) -> dict:
        self._check()
        # Return all stored nodes whose content matches (case-insensitive)
        q = query.lower()
        matched = []
        for content in self._store.values():
            try:
                data = json.loads(content)
                if q in data.get("content", "").lower() or not q:
                    matched.append({"content": content})
            except json.JSONDecodeError:
                pass
        return {"nodes": matched}

    async def memory_list(self, path: str, **kwargs: Any) -> dict:
        self._check()
        prefix = path.rstrip("*").rstrip("/")
        matched = [
            {"content": v}
            for k, v in self._store.items()
            if k.startswith(prefix)
        ]
        return {"nodes": matched}

    async def memory_delete(self, path: str, **_: Any) -> dict:
        self._check()
        if path not in self._store:
            raise KeyError(f"not found: {path}")
        del self._store[path]
        return {"ok": True}

    async def ping(self) -> bool:
        return not self.fail


# ------------------------------------------------------------------
# Helper: build MemoryManager with mock AINDY client
# ------------------------------------------------------------------

def _make_manager(mock_client, backend: str = "aindy"):
    from claw.config.schema import MemoryConfig
    from claw.memory.manager import MemoryManager
    cfg = MemoryConfig(enabled=True, db_path=":memory:")
    return MemoryManager(
        cfg,
        state_dir="~/.claw",
        aindy_client=mock_client,
        aindy_memory_backend=backend,
        aindy_user_id="test-user",
    )


# ------------------------------------------------------------------
# 1. remember() routes to AINDY
# ------------------------------------------------------------------

async def test_remember_routes_to_aindy() -> None:
    print("\n== remember() -> AINDY ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        node = await mgr.remember("agent1", "AINDY memory test", tags=["p2"])
        assert node.id

        # Content must be in AINDY store, not local
        assert any("AINDY memory test" in v for v in client._store.values()), \
            "node not found in AINDY store"
        check("remember() writes to AINDY", PASS, f"node_id={node.id[:8]}...")

        # Local store should NOT have it in aindy-strict mode
        local_node = mgr._store.get(node.id, "agent1")
        assert local_node is None, "node unexpectedly written to local store in aindy mode"
        check("remember() skips local store in strict mode", PASS)

    except Exception as e:
        check("remember() routes to AINDY", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. recall() routes to AINDY search
# ------------------------------------------------------------------

async def test_recall_routes_to_aindy() -> None:
    print("\n== recall() -> AINDY ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        node = await mgr.remember("agent1", "semantic search target content")
        nodes = await mgr.recall("agent1", "semantic search target")
        assert any(n.id == node.id for n in nodes), "recalled nodes don't include written node"
        check("recall() finds node via AINDY search", PASS, f"{len(nodes)} node(s)")

    except Exception as e:
        check("recall() routes to AINDY", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. list_all() routes to AINDY
# ------------------------------------------------------------------

async def test_list_all_routes_to_aindy() -> None:
    print("\n== list_all() -> AINDY ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        await mgr.remember("agent1", "first memory")
        await mgr.remember("agent1", "second memory")

        nodes = await mgr.list_all("agent1")
        assert len(nodes) >= 2, f"expected ≥2 nodes, got {len(nodes)}"
        check("list_all() returns AINDY nodes", PASS, f"{len(nodes)} node(s)")

    except Exception as e:
        check("list_all() routes to AINDY", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. get() routes to AINDY
# ------------------------------------------------------------------

async def test_get_routes_to_aindy() -> None:
    print("\n== get() -> AINDY ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        node = await mgr.remember("agent1", "get test memory")
        fetched = await mgr.get("agent1", node.id)
        assert fetched is not None, "get() returned None"
        assert fetched.content == "get test memory"
        check("get() fetches node from AINDY", PASS)

    except Exception as e:
        check("get() routes to AINDY", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. forget() routes to AINDY
# ------------------------------------------------------------------

async def test_forget_routes_to_aindy() -> None:
    print("\n== forget() -> AINDY ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        node = await mgr.remember("agent1", "node to delete")
        count_before = len(client._store)

        deleted = await mgr.forget("agent1", node.id)
        assert deleted, "forget() returned False"
        assert len(client._store) < count_before, "AINDY store not shrunk after delete"
        check("forget() deletes from AINDY", PASS)

    except Exception as e:
        check("forget() routes to AINDY", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. aindy-fallback mode: AINDY error -> SQLite
# ------------------------------------------------------------------

async def test_aindy_fallback_on_error() -> None:
    print("\n== aindy-fallback mode ==")
    try:
        bad_client = _MockAINDYClient(fail=True)
        from claw.config.schema import MemoryConfig
        from claw.memory.manager import MemoryManager

        cfg = MemoryConfig(enabled=True, db_path=":memory:")
        mgr = MemoryManager(
            cfg,
            aindy_client=bad_client,
            aindy_memory_backend="aindy-fallback",
            aindy_user_id="test-user",
        )

        # remember() should fall back to local SQLite without raising
        node = await mgr.remember("agent1", "fallback memory")
        assert node.id
        check("remember() falls back to local on AINDY error", PASS)

        # local store should have the node (written by fallback)
        local_node = mgr._store.get(node.id, "agent1")
        assert local_node is not None, "fallback node not in local store"
        check("fallback node written to local store", PASS)

        # forget() fallback
        deleted = await mgr.forget("agent1", node.id)
        assert deleted
        check("forget() fallback works", PASS)

    except Exception as e:
        check("aindy-fallback mode", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. aindy strict mode: AINDY error -> raises
# ------------------------------------------------------------------

async def test_aindy_strict_raises() -> None:
    print("\n== aindy strict mode raises ==")
    try:
        bad_client = _MockAINDYClient(fail=True)
        mgr = _make_manager(bad_client, backend="aindy")

        raised = False
        try:
            await mgr.remember("agent1", "should fail")
        except Exception:
            raised = True

        assert raised, "aindy strict mode did not raise on AINDY failure"
        check("aindy strict mode raises on error", PASS)

    except Exception as e:
        check("aindy strict mode", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. local mode: AINDY client ignored
# ------------------------------------------------------------------

async def test_local_mode_ignores_aindy() -> None:
    print("\n== local mode ignores AINDY client ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client, backend="local")

        assert mgr._aindy_store is None, "aindy_store should be None in local mode"

        node = await mgr.remember("agent1", "local memory")
        assert node.id
        assert not client._store, "AINDY store should be empty in local mode"
        check("local mode never calls AINDY", PASS)

        local_node = mgr._store.get(node.id, "agent1")
        assert local_node is not None
        check("local mode writes to local store", PASS)

    except Exception as e:
        check("local mode", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. agent isolation (different agent_ids use different MAS paths)
# ------------------------------------------------------------------

async def test_agent_isolation() -> None:
    print("\n== Agent isolation in AINDY paths ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_manager(client)

        await mgr.remember("alice", "alice private memory")
        await mgr.remember("bob", "bob private memory")

        alice_nodes = await mgr.list_all("alice")
        bob_nodes = await mgr.list_all("bob")

        alice_contents = {n.content for n in alice_nodes}
        bob_contents = {n.content for n in bob_nodes}

        assert "alice private memory" in alice_contents
        assert "bob private memory" not in alice_contents
        assert "bob private memory" in bob_contents
        assert "alice private memory" not in bob_contents
        check("Agent MAS paths are isolated", PASS,
              f"alice={len(alice_nodes)} bob={len(bob_nodes)}")

    except Exception as e:
        check("Agent isolation", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. Regression — existing Phase 6 tests still pass
# ------------------------------------------------------------------

def test_phase6_regression() -> None:
    print("\n== Phase 6 regression ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "tests/test_phase6_milestone.py"],
            capture_output=True, text=True, timeout=180,
        )
        output = r.stdout + r.stderr
        # Phase 6 passes when no FAIL lines appear and exit code is 0
        if r.returncode == 0 and "FAIL" not in output:
            check("Phase 6 milestone regression", PASS)
        else:
            for line in output.splitlines():
                if "Results:" in line:
                    check("Phase 6 milestone regression", FAIL, line.strip())
                    return
            check("Phase 6 milestone regression", FAIL, output[-300:])
    except Exception as e:
        check("Phase 6 regression", FAIL, str(e))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_remember_routes_to_aindy()
    await test_recall_routes_to_aindy()
    await test_list_all_routes_to_aindy()
    await test_get_routes_to_aindy()
    await test_forget_routes_to_aindy()
    await test_aindy_fallback_on_error()
    await test_aindy_strict_raises()
    await test_local_mode_ignores_aindy()
    await test_agent_isolation()


def main() -> None:
    print("=" * 60)
    print("  AINDY Phase 2 — Memory Backend Delegation")
    print("=" * 60)

    asyncio.run(run_async_tests())
    test_phase6_regression()

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
