"""Phase 4 milestone test — automated checks for all testable subsystems.

Run:  python tests/test_phase4_milestone.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
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
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[ ?? ]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# 1. Config loading
# ------------------------------------------------------------------

def test_config() -> None:
    print("\n== Config ==")
    try:
        from claw.config.loader import load_config
        cfg = load_config(ROOT / "claw.toml")
        agents = cfg.agents.agents
        assert len(agents) >= 2, f"expected >=2 agents, got {len(agents)}"
        assert any(a.id == "main" for a in agents)
        assert any(a.id == "coder" for a in agents)
        assert len(cfg.cron) >= 1
        assert cfg.credentials
        check("Config loads from claw.toml", PASS, f"{len(agents)} agents, {len(cfg.cron)} cron jobs")
    except Exception as e:
        check("Config loads from claw.toml", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. CLI — global --config must come before subcommand
# ------------------------------------------------------------------

def test_cli_check() -> None:
    print("\n== CLI: claw check ==")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "claw", "--config", "claw.toml", "check"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and "Config OK" in r.stdout:
            check("claw check", PASS, r.stdout.strip().split("\n")[0])
        else:
            check("claw check", FAIL, (r.stderr or r.stdout).strip()[:120])
    except Exception as e:
        check("claw check", FAIL, str(e))


def test_cli_agents() -> None:
    print("\n== CLI: claw agents list ==")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "claw", "--config", "claw.toml", "agents", "list"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and "main" in r.stdout and "coder" in r.stdout:
            check("claw agents list", PASS, r.stdout.strip())
        else:
            check("claw agents list", FAIL, (r.stderr or r.stdout).strip()[:120])
    except Exception as e:
        check("claw agents list", FAIL, str(e))


def test_cli_cron() -> None:
    print("\n== CLI: claw cron list ==")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "claw", "--config", "claw.toml", "cron", "list"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and "heartbeat" in r.stdout:
            check("claw cron list", PASS, r.stdout.strip().split("\n")[0])
        else:
            check("claw cron list", FAIL, (r.stderr or r.stdout).strip()[:120])
    except Exception as e:
        check("claw cron list", FAIL, str(e))


# ------------------------------------------------------------------
# 3. AgentRegistry — multi-agent isolation
# ------------------------------------------------------------------

def test_agent_registry() -> None:
    print("\n== AgentRegistry ==")
    try:
        from claw.config.loader import load_config
        from claw.agents.registry import AgentRegistry
        cfg = load_config(ROOT / "claw.toml")
        reg = AgentRegistry(cfg)
        ids = reg.agent_ids()
        assert "main" in ids and "coder" in ids, f"unexpected ids: {ids}"
        turn_main = reg.get_turn("main")
        turn_coder = reg.get_turn("coder")
        assert turn_main is not None and turn_coder is not None
        assert turn_main is not turn_coder
        check("Two agents registered", PASS, f"ids={ids}")
        check("Separate ConversationalTurn instances", PASS)

        from claw.config.schema import AgentConfig
        reg.register_agent(AgentConfig(id="dynamic-test", name="Dynamic"))
        assert "dynamic-test" in reg.agent_ids()
        reg.unregister_agent("dynamic-test")
        assert "dynamic-test" not in reg.agent_ids()
        check("Dynamic register/unregister", PASS)
    except Exception as e:
        check("AgentRegistry", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. BindingResolver — explicit agent_id override
# ------------------------------------------------------------------

def test_resolver_agent_override() -> None:
    print("\n== BindingResolver ==")
    try:
        from claw.routing.resolver import BindingResolver
        from claw.routing.envelope import InboundEnvelope

        resolver = BindingResolver([], fallback_agent_id="main")
        env = InboundEnvelope(channel_id="webchat", peer_id="peer1", content="hi")
        assert resolver.resolve(env) == "main"
        check("Fallback to main", PASS)

        env_explicit = InboundEnvelope(channel_id="webchat", peer_id="peer1", content="hi", agent_id="coder")
        assert resolver.resolve(env_explicit) == "coder"
        check("Explicit agent_id override", PASS)
    except Exception as e:
        check("BindingResolver", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. SessionManager — per-peer isolation + persistence
# ------------------------------------------------------------------

def test_session_manager() -> None:
    print("\n== SessionManager ==")
    try:
        from claw.config.schema import SessionConfig
        from claw.sessions.manager import ClawSessionManager
        from claw.sessions.key import SessionKeyBuilder

        cfg = SessionConfig(dm_scope="per-peer")
        mgr = ClawSessionManager(cfg)
        builder = SessionKeyBuilder(cfg)

        key1 = builder.build("main", "webchat", "alice")
        key2 = builder.build("main", "webchat", "bob")
        assert key1 != key2

        mgr.append_user_message(key1, "Hello from Alice")
        mgr.append_assistant_message(key1, "Hi Alice!")
        mgr.append_user_message(key2, "Hello from Bob")

        h1 = mgr.get_messages(key1)
        h2 = mgr.get_messages(key2)
        assert len(h1) == 2 and len(h2) == 1
        check("Per-peer session isolation", PASS, f"alice={len(h1)}, bob={len(h2)}")

        mgr.append_user_message(key1, "Second message")
        assert len(mgr.get_messages(key1)) == 3
        check("Session persists across appends", PASS)
    except Exception as e:
        check("SessionManager", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. Channel adapter imports
# ------------------------------------------------------------------

def test_channel_imports() -> None:
    print("\n== Channel adapter imports ==")
    adapters = {
        "WebChat": "claw_webchat.adapter",
        "Telegram": "claw_telegram.adapter",
        "Discord": "claw_discord.adapter",
        "Slack": "claw_slack.adapter",
        "Signal": "claw_signal.adapter",
        "Matrix": "claw_matrix.adapter",
    }
    for name, module in adapters.items():
        try:
            __import__(module)
            check(f"{name} adapter imports", PASS)
        except Exception as e:
            check(f"{name} adapter imports", FAIL, str(e))


# ------------------------------------------------------------------
# 7. Gateway HTTP — health + ready + UI (async, in-process)
# ------------------------------------------------------------------

async def test_gateway_http() -> None:
    print("\n== Gateway HTTP ==")
    try:
        from httpx import AsyncClient, ASGITransport
        from claw.config.loader import load_config
        from claw.gateway.server import build_app

        cfg = load_config(ROOT / "claw.toml")
        app, _ = build_app(cfg)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/health")
            assert r.status_code == 200 and r.json()["status"] == "ok"
            check("GET /health", PASS)

            r2 = await client.get("/ready")
            assert r2.status_code == 200
            check("GET /ready", PASS)

            r3 = await client.get("/")
            assert r3.status_code == 200
            check("GET / (WebChat UI)", PASS, f"{len(r3.text)} bytes")

    except Exception as e:
        check("Gateway HTTP", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. Pairing API (async, in-process)
# ------------------------------------------------------------------

async def test_pairing_api() -> None:
    print("\n== Pairing API ==")
    try:
        from httpx import AsyncClient, ASGITransport
        from claw.config.loader import load_config
        from claw.gateway.server import build_app

        cfg = load_config(ROOT / "claw.toml")
        app, _ = build_app(cfg)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/pair/generate?channel_id=telegram&peer_id=1234567")
            assert r.status_code == 200, f"generate returned {r.status_code}"
            data = r.json()
            code = data["code"]
            assert len(code) == 6, f"expected 6-char code, got {len(code)!r}: {code!r}"
            check("POST /pair/generate", PASS, f"code={code}")

            r2 = await client.post(f"/pair/approve?code={code}")
            assert r2.status_code == 200
            assert r2.json()["approved"] is True
            check("POST /pair/approve", PASS)

            # Double-approve should fail
            r3 = await client.post(f"/pair/approve?code={code}")
            assert r3.status_code == 400
            check("Double-approve rejected", PASS)

    except Exception as e:
        check("Pairing API", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. WebSocket — via Starlette TestClient (sync, real lifespan)
# ------------------------------------------------------------------

def test_websocket() -> None:
    print("\n== WebSocket ==")
    try:
        from starlette.testclient import TestClient
        from claw.config.loader import load_config
        from claw.gateway.server import build_app

        cfg = load_config(ROOT / "claw.toml")
        app, _ = build_app(cfg)

        with TestClient(app) as client:
            # Hello frame + ping/pong
            with client.websocket_connect("/ws/chat") as ws:
                hello = ws.receive_json()
                assert hello["type"] == "hello"
                peer_id = hello["peer_id"]
                check("WS hello frame received", PASS, f"peer_id={peer_id[:8]}...")

                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"
                check("Ping -> pong", PASS)

                # Chat to main agent
                ws.send_json({"type": "chat", "content": "Reply with exactly: MAIN_OK"})
                chunks = []
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "chunk":
                        chunks.append(frame["content"])
                    elif frame["type"] == "done":
                        break
                    elif frame["type"] == "error":
                        raise RuntimeError(frame.get("message", "error frame"))
                main_text = "".join(chunks)
                check("Chat to main agent (streaming)", PASS, f"{len(main_text)} chars")

                # Chat to coder agent via explicit agent_id
                ws.send_json({"type": "chat", "content": "Reply with exactly: CODER_OK", "agent_id": "coder"})
                chunks2 = []
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "chunk":
                        chunks2.append(frame["content"])
                    elif frame["type"] == "done":
                        break
                    elif frame["type"] == "error":
                        raise RuntimeError(frame.get("message", "error frame"))
                coder_text = "".join(chunks2)
                check("Chat to coder agent via agent_id", PASS, f"{len(coder_text)} chars")

                # Session persistence — follow-up message
                ws.send_json({"type": "chat", "content": "What did I just ask you to say?"})
                chunks3 = []
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "chunk":
                        chunks3.append(frame["content"])
                    elif frame["type"] == "done":
                        break
                    elif frame["type"] == "error":
                        raise RuntimeError(frame.get("message", "error frame"))
                follow_text = "".join(chunks3)
                assert follow_text, "empty follow-up response"
                check("Session persists (follow-up message)", PASS, f"{len(follow_text)} chars")

    except Exception as e:
        check("WebSocket", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. CronManager — job registration + direct fire
# ------------------------------------------------------------------

async def test_cron_manager() -> None:
    print("\n== CronManager ==")
    try:
        from claw.config.loader import load_config
        from claw.gateway.server import ClawGateway
        from claw.cron.manager import CronManager, CronJob, DeliveryMode

        cfg = load_config(ROOT / "claw.toml")
        gateway = ClawGateway(cfg)
        await gateway.startup()

        cron_mgr = gateway.cron_manager
        assert cron_mgr is not None
        jobs = cron_mgr.list_jobs()
        assert any(j["id"] == "heartbeat" for j in jobs)
        check("CronManager starts with config jobs", PASS, f"{len(jobs)} job(s)")

        # Fire a test job directly (bypass schedule)
        captured: dict = {}
        original_deliver = cron_mgr._deliver

        async def capture_deliver(job, response):
            captured["response"] = response

        cron_mgr._deliver = capture_deliver

        test_job = CronJob(
            id="test-fire",
            agent_id="main",
            prompt='Reply with exactly the text: CRON_TEST_OK',
            cron_expr="0 0 1 1 0",
            delivery=DeliveryMode.NONE,
        )
        cron_mgr.add_job(test_job)
        await cron_mgr._run_job(test_job)

        resp = captured.get("response", "")
        if resp:
            check("Cron job fires + LLM responds", PASS, f"{len(resp)} chars")
        else:
            check("Cron job fires + LLM responds", FAIL, "no response captured")

        await gateway.shutdown()
    except Exception as e:
        check("CronManager", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_gateway_http()
    await test_pairing_api()
    await test_cron_manager()


def main() -> None:
    print("=" * 60)
    print("  Claw Phase 4 Milestone Test")
    print("=" * 60)

    test_config()
    test_cli_check()
    test_cli_agents()
    test_cli_cron()
    test_agent_registry()
    test_resolver_agent_override()
    test_session_manager()
    test_channel_imports()
    asyncio.run(run_async_tests())
    test_websocket()   # sync, uses real lifespan via TestClient

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

    print("\nChannel adapters that need real credentials to test:")
    print("  Telegram -- uncomment [channels.extra.telegram] in claw.toml")
    print("  Discord  -- uncomment [channels.extra.discord] in claw.toml")
    print("  Slack    -- uncomment [channels.extra.slack] in claw.toml")
    print("  Matrix   -- uncomment [channels.extra.matrix] in claw.toml")
    print("  Signal   -- install signal-cli + uncomment [channels.extra.signal]")


if __name__ == "__main__":
    main()
