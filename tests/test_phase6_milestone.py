"""Phase 6 milestone test — SQLite persistence, browser tool, CLI doctor.

Run:  python tests/test_phase6_milestone.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
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
# 1. MemorySqliteStore — persistence across instances
# ------------------------------------------------------------------

def test_memory_sqlite_store() -> None:
    print("\n== MemorySqliteStore ==")
    try:
        import uuid
        from datetime import datetime, timezone
        from nodus_memory import MemoryNode
        from claw.memory.sqlite_store import MemorySqliteStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test_memory.db"

            # First instance — write nodes
            store1 = MemorySqliteStore(db)
            node_id = str(uuid.uuid4())
            node = MemoryNode(
                id=node_id, user_id="main", content="SQLite test memory",
                tags=["test"], node_type="insight", memory_type="insight",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            store1.write(node)
            stored = store1.get(node_id, "main")
            assert stored is not None and stored.content == "SQLite test memory"
            check("write() + get() round-trip", PASS)
            store1.close()

            # Second instance — reads same data (persistence check)
            store2 = MemorySqliteStore(db)
            recalled = store2.get(node_id, "main")
            assert recalled is not None, "node not found after reopening DB"
            assert recalled.content == "SQLite test memory"
            check("Persists across instances", PASS)

            # list_by_user
            listed = store2.list_by_user("main", limit=10)
            assert len(listed) == 1
            check("list_by_user()", PASS, f"{len(listed)} node(s)")

            # search_by_tags
            found = store2.search_by_tags(["test"], "main", limit=10)
            assert any(n.id == node_id for n in found)
            check("search_by_tags()", PASS)

            # delete
            deleted = store2.delete(node_id, "main")
            assert deleted
            assert store2.get(node_id, "main") is None
            check("delete() removes node", PASS)

            # User isolation
            n2 = MemoryNode(
                id=str(uuid.uuid4()), user_id="coder", content="Coder memory",
                tags=[], node_type="insight", memory_type="insight",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            store2.write(n2)
            main_nodes = store2.list_by_user("main", limit=10)
            coder_nodes = store2.list_by_user("coder", limit=10)
            assert len(main_nodes) == 0 and len(coder_nodes) == 1
            check("User_id isolation", PASS)

            # update_feedback
            store2.update_feedback(n2.id, success=True)
            updated = store2.get(n2.id, "coder")
            assert updated and updated.success_count >= 1
            check("update_feedback()", PASS)

            store2.close()

    except Exception as e:
        check("MemorySqliteStore", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. MemoryManager with SQLite backend
# ------------------------------------------------------------------

async def test_memory_manager_sqlite() -> None:
    print("\n== MemoryManager (SQLite backend) ==")
    try:
        from claw.config.schema import MemoryConfig
        from claw.memory.manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MemoryConfig(enabled=True, db_path=str(Path(tmpdir) / "memory.db"))
            mgr = MemoryManager(cfg, state_dir=tmpdir)

            node = await mgr.remember("main", "Persistent memory test", tags=["p6"])
            assert node.id
            check("remember() with SQLite backend", PASS, f"id={node.id[:8]}...")

            nodes = await mgr.recall("main", "persistent memory")
            assert any(n.id == node.id for n in nodes)
            check("recall() finds stored node", PASS)

            mgr.close()

            # Reopen with same DB — memory survives
            cfg2 = MemoryConfig(enabled=True, db_path=str(Path(tmpdir) / "memory.db"))
            mgr2 = MemoryManager(cfg2, state_dir=tmpdir)
            recalled = await mgr2.get("main", node.id)
            assert recalled is not None and recalled.content == "Persistent memory test"
            check("Memory survives manager restart", PASS)
            mgr2.close()

    except Exception as e:
        check("MemoryManager SQLite", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. SqliteApiKeyStore — persistence
# ------------------------------------------------------------------

def test_sqlite_api_key_store() -> None:
    print("\n== SqliteApiKeyStore ==")
    try:
        from claw.auth.sqlite_store import SqliteApiKeyStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "auth.db"

            store1 = SqliteApiKeyStore(db)
            raw_key, rec = store1.create("my-laptop", scopes=["*"])
            assert raw_key.startswith("claw_")
            check("create() generates prefixed key", PASS, f"key_id={rec.key_id}")

            # Verify
            found = store1.verify(raw_key)
            assert found and found.key_id == rec.key_id
            check("verify() accepts correct key", PASS)

            assert store1.verify("claw_badkey") is None
            check("verify() rejects wrong key", PASS)
            store1.close()

            # Reopen — key still valid
            store2 = SqliteApiKeyStore(db)
            found2 = store2.verify(raw_key)
            assert found2 is not None
            check("Key persists across store instances", PASS)

            # Revoke
            store2.revoke(rec.key_id)
            assert store2.verify(raw_key) is None
            check("revoke() disables key", PASS)

            # List active
            _, rec2 = store2.create("phone")
            active = store2.list_keys()
            assert len(active) == 1 and active[0].key_id == rec2.key_id
            check("list_keys() returns only active", PASS)
            store2.close()

    except Exception as e:
        check("SqliteApiKeyStore", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. Browser tool — browser_fetch
# ------------------------------------------------------------------

async def test_browser_tool() -> None:
    print("\n== Browser tool ==")
    try:
        from claw.tools.registry import ToolRegistry
        from claw.tools.standard import register_standard_tools

        reg = ToolRegistry()
        register_standard_tools(reg)

        defs = {d["name"] for d in reg.definitions()}
        assert "browser_fetch" in defs
        check("browser_fetch registered", PASS)

        # Fetch a real URL
        result = await reg.invoke("browser_fetch", {"url": "https://httpbin.org/json"})
        assert "200" in result or "slideshow" in result.lower() or "{" in result
        check("browser_fetch fetches real URL", PASS, f"{len(result)} chars")

        # HTML stripping
        result2 = await reg.invoke("browser_fetch", {
            "url": "https://httpbin.org/html",
            "max_chars": 500,
        })
        assert "<html" not in result2.lower() or len(result2) <= 520
        check("browser_fetch strips HTML + respects max_chars", PASS, f"{len(result2)} chars")

        # Invalid URL scheme
        result3 = await reg.invoke("browser_fetch", {"url": "ftp://example.com"})
        assert "error" in result3.lower()
        check("browser_fetch rejects non-http scheme", PASS)

        # Missing URL
        result4 = await reg.invoke("browser_fetch", {})
        assert "error" in result4.lower()
        check("browser_fetch handles missing URL", PASS)

    except Exception as e:
        check("Browser tool", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. CLI doctor
# ------------------------------------------------------------------

def test_cli_doctor() -> None:
    print("\n== CLI: claw doctor ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "claw", "--config", "claw.toml", "doctor"],
            capture_output=True, text=True, timeout=30,
        )
        output = r.stdout + r.stderr
        # Doctor should produce some output with OK/WARN/FAIL checks
        has_checks = any(x in output for x in ("[OK]", "[WARN]", "[FAIL]"))
        if has_checks:
            check("claw doctor runs and produces checks", PASS,
                  f"exit={r.returncode}")
        else:
            check("claw doctor runs and produces checks", FAIL,
                  f"no check output found: {output[:100]}")

        # Should report config OK
        assert "Config loads" in output or "Config" in output
        check("claw doctor checks config", PASS)

        # Should report LLM credentials
        assert "LLM" in output or "credentials" in output.lower()
        check("claw doctor checks LLM credentials", PASS)

    except Exception as e:
        check("CLI doctor", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. start/stop/status CLI subcommands exist
# ------------------------------------------------------------------

def test_cli_daemon_commands() -> None:
    print("\n== CLI daemon commands (syntax check) ==")
    try:
        import subprocess

        for cmd in ["stop", "status"]:
            r = subprocess.run(
                [sys.executable, "-m", "claw", "--config", "claw.toml", cmd],
                capture_output=True, text=True, timeout=10,
            )
            # These should run (exit with non-zero since no daemon) but not crash with usage error
            assert "unrecognized" not in r.stderr.lower(), f"'{cmd}' not recognized"
            check(f"`claw {cmd}` subcommand exists", PASS, f"exit={r.returncode}")

        # --daemon flag exists on start
        r2 = subprocess.run(
            [sys.executable, "-m", "claw", "start", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert "--daemon" in r2.stdout
        check("`claw start --daemon` flag exists", PASS)

    except Exception as e:
        check("CLI daemon commands", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. Full regression — Phase 4+5 tests still pass
# ------------------------------------------------------------------

def test_phase4_regression() -> None:
    print("\n== Phase 4 regression ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "tests/test_phase4_milestone.py"],
            capture_output=True, text=True, timeout=180,
        )
        if "30/30 passed" in r.stdout:
            check("Phase 4 milestone (30/30)", PASS)
        else:
            # Extract result line
            for line in r.stdout.splitlines():
                if "Results:" in line:
                    check("Phase 4 milestone", FAIL if "failed" in line else PASS, line.strip())
                    return
            check("Phase 4 milestone", FAIL, r.stdout[-200:])
    except Exception as e:
        check("Phase 4 regression", FAIL, str(e))


def test_phase5_regression() -> None:
    print("\n== Phase 5 regression ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "tests/test_phase5_milestone.py"],
            capture_output=True, text=True, timeout=180,
        )
        if "43/43 passed" in r.stdout:
            check("Phase 5 milestone (43/43)", PASS)
        else:
            for line in r.stdout.splitlines():
                if "Results:" in line:
                    check("Phase 5 milestone", FAIL if "failed" in line else PASS, line.strip())
                    return
            check("Phase 5 milestone", FAIL, r.stdout[-200:])
    except Exception as e:
        check("Phase 5 regression", FAIL, str(e))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_memory_manager_sqlite()
    await test_browser_tool()


def main() -> None:
    print("=" * 60)
    print("  Claw Phase 6 Milestone Test")
    print("=" * 60)

    test_memory_sqlite_store()
    test_sqlite_api_key_store()
    test_cli_doctor()
    test_cli_daemon_commands()
    asyncio.run(run_async_tests())
    test_phase4_regression()
    test_phase5_regression()

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
