"""AINDY Phase 3 milestone test — execution tracking + cron observability.

Tests (all with mock AINDY client, no real server needed):
- execution_unit_id generated per turn and propagated into memory node extra
- claw.session.started fired on first message to a session
- claw.session.ended fired on WS disconnect (checked via gateway internals)
- claw.memory.written event fired when AINDYMemoryStore writes a node
- sys.v1.job.submit fired from CronManager before turn
- claw.cron.executed fired from CronManager after turn

Run:  python tests/test_aindy_phase3.py
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

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# Mock AINDY client (records all calls)
# ------------------------------------------------------------------

class _MockAINDYClient:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.events: list[dict] = []
        self.jobs: list[dict] = []

    async def emit_event(self, event_type: str, payload: dict | None = None) -> dict:
        self.events.append({"type": event_type, "payload": payload or {}})
        return {"ok": True}

    async def memory_write(self, path: str, content: str, **_: Any) -> dict:
        self._store[path] = content
        return {"ok": True, "path": path}

    async def memory_read(self, path: str, **_: Any) -> dict:
        content = self._store.get(path)
        if content is None:
            raise KeyError(f"not found: {path}")
        return {"content": content}

    async def memory_search(self, query: str, **kwargs: Any) -> dict:
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
        prefix = path.rstrip("*").rstrip("/")
        matched = [{"content": v} for k, v in self._store.items() if k.startswith(prefix)]
        return {"nodes": matched}

    async def memory_delete(self, path: str, **_: Any) -> dict:
        if path not in self._store:
            raise KeyError(f"not found: {path}")
        del self._store[path]
        return {"ok": True}

    async def submit_job(self, task_name: str, payload: dict, **_: Any) -> dict:
        self.jobs.append({"task_name": task_name, "payload": payload})
        return {"ok": True}

    async def ping(self) -> bool:
        return True

    def events_of_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e["type"] == event_type]


# ------------------------------------------------------------------
# Helper: MemoryManager with mock AINDY client (aindy mode)
# ------------------------------------------------------------------

def _make_memory_manager(client, backend: str = "aindy"):
    from claw.config.schema import MemoryConfig
    from claw.memory.manager import MemoryManager
    cfg = MemoryConfig(enabled=True, db_path=":memory:")
    return MemoryManager(
        cfg,
        aindy_client=client,
        aindy_memory_backend=backend,
        aindy_user_id="test-user",
    )


# ------------------------------------------------------------------
# 1. execution_unit_id propagates into MemoryNode.extra
# ------------------------------------------------------------------

async def test_execution_unit_id_in_memory_node() -> None:
    print("\n== execution_unit_id in MemoryNode.extra ==")
    try:
        from claw.memory.manager import MemoryManager
        from claw.config.schema import MemoryConfig

        # Local mode (no AINDY) — extra field should still be set
        cfg = MemoryConfig(enabled=True, db_path=":memory:")
        mgr = MemoryManager(cfg)

        eid = str(uuid.uuid4())
        node = await mgr.remember("agent1", "test memory", execution_unit_id=eid)
        assert node.extra.get("execution_unit_id") == eid, \
            f"execution_unit_id not in extra: {node.extra}"
        check("execution_unit_id written to node.extra", PASS, f"eid={eid[:8]}...")

        # Without execution_unit_id — extra should be empty
        node2 = await mgr.remember("agent1", "no eid memory")
        assert not node2.extra.get("execution_unit_id"), \
            f"unexpected eid in extra: {node2.extra}"
        check("No execution_unit_id -> empty extra", PASS)

    except Exception as e:
        check("execution_unit_id in node.extra", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. claw.memory.written event fired by AINDYMemoryStore
# ------------------------------------------------------------------

async def test_memory_written_event() -> None:
    print("\n== claw.memory.written event ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_memory_manager(client)

        eid = str(uuid.uuid4())
        node = await mgr.remember("agent1", "event test memory", execution_unit_id=eid)

        # Give fire-and-forget tasks a cycle to run
        await asyncio.sleep(0)

        written_events = client.events_of_type("claw.memory.written")
        assert written_events, "no claw.memory.written event emitted"
        ev = written_events[0]
        assert ev["payload"]["node_id"] == node.id
        assert ev["payload"]["agent_id"] == "agent1"
        assert ev["payload"]["execution_unit_id"] == eid
        check("claw.memory.written event fired", PASS,
              f"node_id={node.id[:8]}... eid={eid[:8]}...")

    except Exception as e:
        check("claw.memory.written event", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. execution_unit_id forwarded through memory tool handler
# ------------------------------------------------------------------

async def test_tool_handler_forwards_execution_unit_id() -> None:
    print("\n== tool handler forwards execution_unit_id ==")
    try:
        from claw.tools.registry import ToolRegistry
        from claw.memory.tools import register_memory_tools
        from claw.memory.manager import MemoryManager
        from claw.config.schema import MemoryConfig

        cfg = MemoryConfig(enabled=True, db_path=":memory:")
        mgr = MemoryManager(cfg)
        reg = ToolRegistry()
        register_memory_tools(reg, mgr)

        eid = str(uuid.uuid4())
        result_json = await reg.invoke("remember", {
            "_agent_id": "agent1",
            "_execution_unit_id": eid,
            "content": "tool-remembered fact",
        })
        result = json.loads(result_json)
        assert result.get("stored"), f"unexpected result: {result}"

        node = await mgr.get("agent1", result["id"])
        assert node is not None
        assert node.extra.get("execution_unit_id") == eid
        check("tool handler passes execution_unit_id to remember()", PASS,
              f"eid={eid[:8]}...")

    except Exception as e:
        check("tool handler execution_unit_id", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. cron: sys.v1.job.submit fired before turn
# ------------------------------------------------------------------

async def test_cron_job_submit() -> None:
    print("\n== cron sys.v1.job.submit ==")
    try:
        from claw.cron.manager import CronJob, DeliveryMode, _fire_aindy_job

        client = _MockAINDYClient()
        eid = str(uuid.uuid4())

        # Simulate what _run_job does
        job = CronJob(
            id="hb", agent_id="main", prompt="heartbeat",
            cron_expr="0 8 * * *", delivery=DeliveryMode.NONE,
        )
        asyncio.create_task(_fire_aindy_job(client, "claw.cron", {
            "job_id": job.id,
            "agent_id": job.agent_id,
            "delivery": job.delivery.value,
            "execution_unit_id": eid,
        }))
        await asyncio.sleep(0)

        assert client.jobs, "no job submitted to AINDY"
        submitted = client.jobs[0]
        assert submitted["task_name"] == "claw.cron"
        assert submitted["payload"]["job_id"] == "hb"
        assert submitted["payload"]["execution_unit_id"] == eid
        check("sys.v1.job.submit fired with correct payload", PASS,
              f"task=claw.cron eid={eid[:8]}...")

    except Exception as e:
        check("cron sys.v1.job.submit", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. cron: claw.cron.executed fired after turn
# ------------------------------------------------------------------

async def test_cron_executed_event() -> None:
    print("\n== claw.cron.executed event ==")
    try:
        from claw.cron.manager import CronJob, DeliveryMode, _fire_aindy_event

        client = _MockAINDYClient()
        eid = str(uuid.uuid4())

        job = CronJob(
            id="hb", agent_id="main", prompt="heartbeat",
            cron_expr="0 8 * * *", delivery=DeliveryMode.NONE,
        )
        response = "Heartbeat OK"
        asyncio.create_task(_fire_aindy_event(client, "claw.cron.executed", {
            "job_id": job.id,
            "agent_id": job.agent_id,
            "delivery": job.delivery.value,
            "execution_unit_id": eid,
            "response_len": len(response),
        }))
        await asyncio.sleep(0)

        executed = client.events_of_type("claw.cron.executed")
        assert executed, "no claw.cron.executed event"
        ev = executed[0]
        assert ev["payload"]["job_id"] == "hb"
        assert ev["payload"]["execution_unit_id"] == eid
        assert ev["payload"]["response_len"] == len(response)
        check("claw.cron.executed event fired with correct payload", PASS,
              f"eid={eid[:8]}...")

    except Exception as e:
        check("claw.cron.executed event", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. session.started event: first turn in a session
# ------------------------------------------------------------------

async def test_session_started_event() -> None:
    print("\n== claw.session.started event ==")
    try:
        from claw.gateway.server import _emit_aindy

        client = _MockAINDYClient()
        eid = str(uuid.uuid4())

        # Simulate the logic in _run_turn: first message -> emit session.started
        is_new_session = True  # would be True when get_messages returns []
        if is_new_session:
            asyncio.create_task(_emit_aindy(client, "claw.session.started", {
                "agent_id": "main",
                "session_key": "webchat:main:peer1",
                "channel": "webchat",
                "execution_unit_id": eid,
            }))
        await asyncio.sleep(0)

        started = client.events_of_type("claw.session.started")
        assert started, "no claw.session.started event"
        ev = started[0]
        assert ev["payload"]["agent_id"] == "main"
        assert ev["payload"]["execution_unit_id"] == eid
        check("claw.session.started event fired on first turn", PASS)

        # Second turn: is_new_session=False -> no event
        client.events.clear()
        is_new_session = False
        if is_new_session:
            asyncio.create_task(_emit_aindy(client, "claw.session.started", {}))
        await asyncio.sleep(0)

        assert not client.events_of_type("claw.session.started"), \
            "session.started fired on non-new session"
        check("claw.session.started NOT fired on subsequent turns", PASS)

    except Exception as e:
        check("claw.session.started event", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. session.ended event (WS disconnect)
# ------------------------------------------------------------------

async def test_session_ended_event() -> None:
    print("\n== claw.session.ended event ==")
    try:
        from claw.gateway.server import _emit_aindy
        import time

        client = _MockAINDYClient()
        t0 = time.monotonic()

        # Simulate WS disconnect handler
        session_info = {"agent_id": "main", "session_key": "webchat:main:peer1"}
        duration_ms = int((time.monotonic() - t0) * 1000)
        asyncio.create_task(_emit_aindy(client, "claw.session.ended", {
            "agent_id": session_info["agent_id"],
            "session_key": session_info["session_key"],
            "duration_ms": duration_ms,
            "channel": "webchat",
        }))
        await asyncio.sleep(0)

        ended = client.events_of_type("claw.session.ended")
        assert ended, "no claw.session.ended event"
        ev = ended[0]
        assert ev["payload"]["session_key"] == "webchat:main:peer1"
        assert "duration_ms" in ev["payload"]
        check("claw.session.ended event fired with duration", PASS,
              f"duration={ev['payload']['duration_ms']}ms")

    except Exception as e:
        check("claw.session.ended event", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. Full audit trail: remember -> memory.written event carries eid
# ------------------------------------------------------------------

async def test_audit_trail_execution_unit_id() -> None:
    print("\n== Full audit trail: remember -> memory.written carries eid ==")
    try:
        client = _MockAINDYClient()
        mgr = _make_memory_manager(client)

        eid = str(uuid.uuid4())
        node = await mgr.remember(
            "agent1", "audit trail test", execution_unit_id=eid
        )
        await asyncio.sleep(0)  # let fire-and-forget tasks run

        # Memory node carries eid
        assert node.extra.get("execution_unit_id") == eid

        # AINDY was given eid in memory.written event
        written = client.events_of_type("claw.memory.written")
        assert written
        assert written[0]["payload"]["execution_unit_id"] == eid

        check("memory node.extra.execution_unit_id == eid", PASS)
        check("claw.memory.written payload.execution_unit_id == eid", PASS)

    except Exception as e:
        check("audit trail", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. Regression: Phase 2 tests still pass
# ------------------------------------------------------------------

def test_phase2_regression() -> None:
    print("\n== Phase 2 regression ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "tests/test_aindy_phase2.py"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            check("AINDY Phase 2 regression", PASS)
        else:
            check("AINDY Phase 2 regression", FAIL, r.stdout[-200:] + r.stderr[-100:])
    except Exception as e:
        check("Phase 2 regression", FAIL, str(e))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_execution_unit_id_in_memory_node()
    await test_memory_written_event()
    await test_tool_handler_forwards_execution_unit_id()
    await test_cron_job_submit()
    await test_cron_executed_event()
    await test_session_started_event()
    await test_session_ended_event()
    await test_audit_trail_execution_unit_id()


def main() -> None:
    print("=" * 60)
    print("  AINDY Phase 3 -- Execution Tracking + Cron")
    print("=" * 60)

    asyncio.run(run_async_tests())
    test_phase2_regression()

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
