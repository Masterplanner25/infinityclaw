# Claw → A.I.N.D.Y. Integration Plan

**Baseline**: Nodus-native Claw (post-OpenClaw rewrite)  
**Runtime**: aindy-runtime 1.4.0 / nodus-lang 4.0.5  
**Date**: 2026-06-19

---

## Executive Summary

Claw and A.I.N.D.Y. are complementary, not competitive. A.I.N.D.Y. is an execution
kernel — syscall dispatch, durable execution, MAS memory, event bus, plugin sandbox,
observability. Claw is a conversational application — Anthropic streaming, workspace
identity, channel adapters, skill discovery, routing logic.

The integration model is **layered**:

```
┌─────────────────────────────────────────────────────┐
│                  Claw Application                   │
│  (agents · sessions · channels · skills · routing)  │
├─────────────────────────────────────────────────────┤
│              Claw ↔ A.I.N.D.Y. SDK Layer            │
│    (AINDYClient · asyncio.to_thread wrappers)       │
├──────────────────────────┬──────────────────────────┤
│    Nodus Language Layer  │  A.I.N.D.Y. Runtime      │
│  (nodus-lang · nodus-*   │  (syscall kernel · MAS   │
│   packages · workflows)  │   events · execution)    │
└──────────────────────────┴──────────────────────────┘
```

A.I.N.D.Y. owns: durable memory, event bus, execution tracking, job scheduling,
observability, plugin sandbox.  
Nodus owns: language VM, agent executor, session protocol, LLM failover, MCP.  
Claw owns: Anthropic streaming turn, workspace identity, channel adapters, skills,
routing, WebChat gateway.

---

## Module Disposition Table

| Module | Files | Disposition | Rationale |
|---|---|---|---|
| `agents/registry.py` | 1 | **Keep** | Nodus-native; AINDY AgentRun is execution history, not live instance registry |
| `agents/turn.py` | 1 | **Keep** | Anthropic streaming + tool loop; AINDY uses OpenAI |
| `agents/prompt.py` | 1 | **Keep** | OpenClaw-specific workspace assembly |
| `agents/streaming.py` | 1 | **Keep** | Utility; no equivalent |
| `auth/manager.py` | 1 | **Keep → Replace (Phase 4)** | Keep for standalone; replace with AINDY `require_execution_context` if gateway mounts |
| `auth/sqlite_store.py` | 1 | **Keep → Delete (Phase 4)** | Same as above |
| `auth/store.py` | 1 | **Keep → Delete (Phase 4)** | Same as above |
| `channels/` | 4 | **Keep** | No AINDY equivalent; OpenClaw-specific |
| `config/schema.py` | 1 | **Integrate** | Add `[aindy]` section |
| `config/loader.py` | 1 | **Keep** | |
| `cron/manager.py` | 1 | **Integrate** | Emit to AINDY job bus; keep turn pipeline |
| `gateway/server.py` | 1 | **Integrate + Fix** | Add OTel; fix `on_event` → `lifespan`; add AINDY event emission |
| `gateway/auth.py` | 1 | **Keep → Replace (Phase 4)** | |
| `gateway/protocol.py` | 1 | **Keep** | |
| `memory/manager.py` | 1 | **Integrate** | Swap to AINDY MAS backend |
| `memory/sqlite_store.py` | 1 | **Keep as fallback** | Dev/offline mode only after Phase 2 |
| `memory/tools.py` | 1 | **Integrate** | Wire to `sys.v1.memory.*` |
| `memory/injector.py` | 1 | **Keep** | Pure formatting |
| `routing/` | 3 | **Keep** | OpenClaw-specific binding resolution |
| `sessions/manager.py` | 1 | **Keep** | Nodus session protocol; AINDY has no conversation history |
| `sessions/compactor.py` | 1 | **Keep** | No AINDY equivalent |
| `sessions/key.py` | 1 | **Keep** | |
| `sessions/identity.py` | 1 | **Keep** | |
| `sessions/pruner.py` | 1 | **Keep** | |
| `skills/` | 4 | **Keep** | No AINDY equivalent; OpenClaw-specific |
| `tools/registry.py` | 1 | **Keep** | Anthropic tool format; distinct from AINDY syscalls |
| `tools/standard.py` | 1 | **Keep** | |
| `workspace/` | 3 | **Keep** | No AINDY equivalent |
| `cli.py` | 1 | **Keep + extend** | Add `claw aindy` doctor subcommand |

**Summary**: 34 files keep, 10 files integrate, 3 files replace in Phase 4, 0 files delete in Phases 1–3.

---

## Syscall Mapping

### Memory

```
claw MemoryManager.remember(content, tags, agent_id)
  → sys.v1.memory.write
  → path: /memory/{user_id}/claw/{agent_id}/{node_type}/{node_id}
  → Migration: Phase 2 — AINDYMemoryStore backend
```

```
claw MemoryManager.recall(query, agent_id)
  → sys.v1.memory.search (semantic) or sys.v1.memory.read (path)
  → Migration: Phase 2
```

```
claw MemoryManager.list_all(agent_id)
  → sys.v1.memory.list
  → path: /memory/{user_id}/claw/{agent_id}/*
  → Migration: Phase 2
```

```
claw MemoryManager.get(node_id)
  → sys.v1.memory.read
  → path: /memory/{user_id}/claw/{agent_id}/**/{node_id}
  → Migration: Phase 2
```

### Scheduling

```
claw CronManager job trigger
  → sys.v1.job.submit (task_name="claw.cron", payload={job_id, ...})
  → Execution tracked in AINDY AutomationLog
  → Migration: Phase 3
```

### Events (additive — currently absent from Claw)

```
(new) turn completed
  → sys.v1.event.emit("claw.turn.completed", {agent_id, session_key, token_count})

(new) memory written
  → sys.v1.event.emit("claw.memory.written", {agent_id, node_id, path})

(new) session started / ended
  → sys.v1.event.emit("claw.session.started", {agent_id, session_key, channel})
  → sys.v1.event.emit("claw.session.ended", {agent_id, session_key, duration_ms})

(new) cron executed
  → sys.v1.event.emit("claw.cron.executed", {job_id, agent_id, delivery_mode})
```

### Execution Tracking (additive)

```
(new) ConversationalTurn.run()
  → sys.v1.execution.get tracking
  → Creates logical execution_unit_id per turn for OTel trace correlation
```

### No Migration (keep Claw-native)

```
Agent LLM streaming        → NOT sys.v1.agent.execute  (AINDY uses OpenAI; Claw uses Anthropic)
Tool execution             → NOT sys.v1.nodus.execute   (Anthropic tool_use format; not Nodus)
Session history storage    → NOT AINDY execution records (AINDY has no conversation history)
WebSocket protocol         → NOT AINDY platform router  (Phases 1-3; optional Phase 4)
Skills discovery           → NOT AINDY extensions       (SKILL.md format is OpenClaw-specific)
Channel adapters           → NOT AINDY routing          (no AINDY channel concept)
```

---

## Components: Detailed Disposition

### 1. Keep As-Is

These modules are OpenClaw-specific with no AINDY equivalent, or are already Nodus-native.

**`claw/agents/`** — The `ConversationalTurn` + `AgentRegistry` stack is the core differentiator.
AINDY's `sys.v1.agent.execute` targets its own OpenAI-backed deterministic runtime; it has no
knowledge of Anthropic streaming, tool loops, or Claw's workspace identity. No change.

**`claw/channels/`** — Telegram, Discord, Slack, Signal, Matrix via `nodus_adapter_base`.
AINDY has no channel adapter layer. `PairingStore` and `DmPolicyEnforcer` are also
OpenClaw-specific. No change.

**`claw/routing/`** — 8-tier `BindingResolver` with per-binding match weights. Entirely
OpenClaw-specific. No AINDY routing equivalent exists.

**`claw/sessions/`** — `ClawSessionManager` wraps `nodus_session.SessionManager` which is
already Nodus-native. The `asyncio.Lock` per session key, `ContextCompactor`, and
`ContextPruner` are conversation-management concerns with no AINDY equivalent. No change.

**`claw/skills/`** — `SKILL.md` discovery and injection into the system prompt. OpenClaw
concept. AINDY's extension system targets plugin code execution, not prompt-injected skill
manifests. No change.

**`claw/tools/`** — Anthropic-format tool definitions wired through `ConversationalTurn`.
AINDY syscalls serve a different purpose (runtime kernel operations). No overlap. No change.

**`claw/workspace/`** — Markdown identity file loading and workspace directory management.
Entirely OpenClaw-specific. No change.

---

### 2. Integrate with A.I.N.D.Y.

#### 2a. Config — add `[aindy]` section

**File**: `claw/config/schema.py`

Add to `ClawConfig`:

```python
class AINDYConfig(BaseModel):
    enabled: bool = False
    url: str = "http://localhost:8000"
    api_key: str = ""           # aindy_* platform key or JWT
    memory_backend: str = "local"   # "local" | "aindy" | "aindy-fallback"
    emit_events: bool = True
    track_execution: bool = True

class ClawConfig(BaseModel):
    ...
    aindy: AINDYConfig = AINDYConfig()
```

Add to `claw.toml`:

```toml
[aindy]
enabled = false
url = "http://localhost:8000"
api_key = ""
memory_backend = "local"
emit_events = true
track_execution = true
```

---

#### 2b. AINDY Client Wrapper

**New file**: `claw/aindy/client.py`

Thin async wrapper around `aindy_sdk.AINDYClient`. The SDK is synchronous; all calls
go through `asyncio.to_thread()`. Singleton per process.

```python
# claw/aindy/client.py

import asyncio
from functools import cached_property
from typing import Any

from aindy_sdk import AINDYClient as _SyncClient

_instance: "_AsyncAINDYClient | None" = None


class _AsyncAINDYClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._sync = _SyncClient(base_url=base_url, api_key=api_key)

    async def emit_event(self, event_type: str, payload: dict) -> dict:
        return await asyncio.to_thread(
            self._sync.events.emit, event_type, payload
        )

    async def memory_write(self, path: str, content: str, **kw) -> dict:
        return await asyncio.to_thread(
            self._sync.memory.write, path, content, **kw
        )

    async def memory_read(self, path: str, **kw) -> dict:
        return await asyncio.to_thread(
            self._sync.memory.read, path, **kw
        )

    async def memory_search(self, query: str, **kw) -> dict:
        return await asyncio.to_thread(
            self._sync.memory.search, query, **kw
        )

    async def memory_list(self, path: str, **kw) -> dict:
        return await asyncio.to_thread(
            self._sync.memory.list, path, **kw
        )

    async def submit_job(self, task_name: str, payload: dict, **kw) -> dict:
        return await asyncio.to_thread(
            self._sync.syscalls.call,
            "sys.v1.job.submit",
            {"task_name": task_name, "payload": payload, **kw},
        )

    async def sandbox_posture(self) -> dict:
        return await asyncio.to_thread(self._sync.sandbox.posture)


def get_aindy_client(url: str, api_key: str) -> "_AsyncAINDYClient":
    global _instance
    if _instance is None:
        _instance = _AsyncAINDYClient(url, api_key)
    return _instance
```

---

#### 2c. Memory — AINDY MAS Backend

**New file**: `claw/aindy/memory_store.py`

Implements `nodus_memory.MemoryStore` protocol backed by AINDY syscalls. Registered as
the active backend when `memory.backend = "aindy"` or `"aindy-fallback"`.

MAS path convention:

```
/memory/{user_id}/claw/{agent_id}/{node_type}/{node_id}
```

The `user_id` for Claw is the gateway identity (single-user mode: configured user ID;
multi-user mode: JWT sub claim). `agent_id` provides namespace isolation between agents.

**Integration points**:

- `memory/manager.py` — add backend selection in `__init__`:
  ```python
  if aindy_client and config.aindy.memory_backend in ("aindy", "aindy-fallback"):
      store = AINDYMemoryStore(aindy_client, user_id, fallback=local_store)
  else:
      store = local_store
  ```

- `memory/tools.py` — no changes required; tools call `MemoryManager` which routes to
  whichever store is active.

**Fallback behaviour**: `"aindy-fallback"` mode writes to AINDY and falls back to SQLite
on `NetworkError` or `ServerError`. `"aindy"` mode hard-fails on AINDY unavailability.
`"local"` mode never calls AINDY (default; zero new infrastructure requirement).

---

#### 2d. Events — lifecycle emission

**File**: `claw/gateway/server.py`

Add `sys.v1.event.emit` calls at 5 points in `_run_turn()` and `ClawGateway.startup()`.
All calls are fire-and-forget: wrapped in `asyncio.create_task()` with a swallowed
exception so a dead AINDY runtime never blocks a turn.

```python
async def _emit(client, event_type, payload):
    try:
        await client.emit_event(event_type, payload)
    except Exception:
        pass   # non-fatal; AINDY unavailability never blocks a turn

# In _run_turn(), before streaming:
asyncio.create_task(_emit(aindy, "claw.turn.started", {
    "agent_id": agent_id, "session_key": session_key,
}))

# In _run_turn(), after streaming:
asyncio.create_task(_emit(aindy, "claw.turn.completed", {
    "agent_id": agent_id, "session_key": session_key,
    "stop_reason": stop_reason,
}))
```

---

#### 2e. Scheduling — AINDY job tracking

**File**: `claw/cron/manager.py`

Wrap each cron execution with `sys.v1.job.submit` so runs appear in AINDY's
`AutomationLog`. The conversational pipeline (workspace load → skill inject →
memory recall → turn) stays in `CronManager` — AINDY only provides the audit record.

```python
# Before executing the turn:
if aindy_client:
    asyncio.create_task(aindy_client.submit_job(
        "claw.cron",
        {"job_id": job.id, "agent_id": job.agent_id, "delivery": job.delivery.value},
        source="cron",
    ))
```

---

#### 2f. Gateway — fix `on_event` + add OTel

**File**: `claw/gateway/server.py`

Two mandatory changes regardless of AINDY phase:

1. **Migrate `@app.on_event` → `lifespan`** (FastAPI 0.137.1 deprecation warning is live now):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await gateway.startup()
    yield
    await gateway.shutdown()

app = FastAPI(lifespan=lifespan)
```

2. **Add FastAPI OTel instrumentation** (package already in venv via aindy-runtime dep):

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)
```

These two changes are Phase 1 prerequisites; they unblock Phase 4 (gateway mount).

---

### 3. Replace with A.I.N.D.Y. (Phase 4 — Gateway Mount)

Phase 4 is optional and requires AINDY running with Postgres + Redis. It transforms
Claw from a standalone FastAPI app into an AINDY application.

**What gets replaced**:

| Claw Component | AINDY Replacement |
|---|---|
| `claw/auth/manager.py` | `AINDY.core.execution_guard.require_execution_context` |
| `claw/auth/sqlite_store.py` | AINDY `SqliteApiKeyStore` (already exists) |
| `claw/auth/store.py` | AINDY in-memory API key store |
| `GET /health`, `GET /ready` | AINDY `/health`, `/health/detail`, `/health/sandbox` |
| Prometheus stub (if added) | AINDY `/metrics` with custom `REGISTRY` |
| Uvicorn startup in `cli.py` | AINDY `main.py` / `create_app()` with Claw routers mounted |

**Mount mechanism**:

```python
# claw/aindy/app_registration.py
from AINDY.platform_layer.registry import register_router

def register_claw_app():
    from claw.gateway.server import _claw_router  # extracted from build_app()
    register_router(_claw_router, prefix="/claw")
```

Claw's WebSocket, pairing, and domain routes then live at `/apps/claw/...` inside the
AINDY runtime. AINDY's `require_execution_context` dependency wraps all routes.
OTel, Prometheus, rate limiting (SlowAPI), and structured logging are inherited.

---

### 4. Delete

**Nothing is deleted in Phases 1–3.**

In Phase 4 only, after gateway mount is confirmed stable:

- `claw/auth/manager.py` (~80 lines)
- `claw/auth/sqlite_store.py` (~120 lines)
- `claw/auth/store.py` (~60 lines)
- Health route handlers in `gateway/server.py` (~30 lines)

Total Phase 4 deletion: ~290 lines.

---

## Runtime Boundary Diagram

```
 ┌──────────────────────────────────────────────────────────────────┐
 │  CHANNEL LAYER                                                   │
 │  Telegram · Discord · Slack · Signal · Matrix · WebChat (WS)    │
 │  claw/channels/ + claw_*/adapters  [nodus_adapter_base]         │
 └─────────────────────────────┬────────────────────────────────────┘
                               │ InboundEnvelope
 ┌─────────────────────────────▼────────────────────────────────────┐
 │  CLAW GATEWAY  [claw/gateway/server.py]                          │
 │  FastAPI · WebSocket · GatewayAuth · ClawGateway                 │
 │                                                                  │
 │  ┌─────────────────┐    ┌──────────────────────────────────────┐ │
 │  │  BindingResolver│    │  _run_turn()                         │ │
 │  │  (routing/)     │    │  workspace → skills → memory recall  │ │
 │  └────────┬────────┘    │  → system prompt → session messages  │ │
 │           │ agent_id    │  → compact → prune → turn.run()      │ │
 │           └─────────────►  → deliver                           │ │
 │                         └──────────────┬─────────────────────--┘ │
 └──────────────────────────┬─────────────┼────────────────────────-┘
                            │             │
         ┌──────────────────▼──┐    ┌─────▼──────────────────────┐
         │  NODUS LAYER         │    │  A.I.N.D.Y. SDK LAYER      │
         │  nodus_llm           │    │  claw/aindy/client.py      │
         │  nodus_session       │    │  (asyncio.to_thread)       │
         │  nodus_memory        │    └─────┬──────────────────────┘
         │  nodus_agent         │          │ HTTP
         │  nodus_mcp           │    ┌─────▼──────────────────────┐
         └──────────────────────┘    │  A.I.N.D.Y. RUNTIME        │
                                     │  aindy-runtime 1.4.0       │
                                     │                            │
                                     │  SyscallDispatcher         │
                                     │  ├─ sys.v1.memory.*       │
                                     │  ├─ sys.v1.event.emit     │
                                     │  ├─ sys.v1.job.submit     │
                                     │  └─ sys.v1.execution.get  │
                                     │                            │
                                     │  MAS (PostgreSQL+pgvector) │
                                     │  EventBus (Redis)          │
                                     │  APScheduler               │
                                     │  OTel · Prometheus         │
                                     └────────────────────────────┘
```

**Phase 4 boundary shift**: The CLAW GATEWAY box moves inside the A.I.N.D.Y. RUNTIME box,
mounted at `/apps/claw`. The SDK layer collapses (direct in-process function calls replace
HTTP). OTel, Prometheus, auth, and health are inherited.

---

## Estimated Code Reduction

| Phase | New Code | Removed Code | Net |
|---|---|---|---|
| Phase 1 (SDK + events + lifespan fix) | +~180 lines | 0 | +180 |
| Phase 2 (memory backend) | +~250 lines | 0 (SQLite becomes optional) | +250 |
| Phase 3 (cron tracking) | +~40 lines | 0 | +40 |
| Phase 4 (gateway mount) | +~60 lines (registration) | -~290 lines (auth + health) | -230 |
| **Total** | **+530** | **-290** | **+240 net** |

Net code *increases* slightly because the integration wiring is additive in Phases 1–3.
The reduction comes in Phase 4. The real gains are architectural:

- Memory durability: SQLite in-process → Postgres with pgvector (semantic search)
- Observability: zero → full OTel + Prometheus (inherited from AINDY)
- Execution audit: zero → complete turn/job history in AINDY AutomationLog
- Event bus: zero → Redis-backed SystemEvents for cross-service integration
- Auth: bespoke JWT/SQLite → AINDY platform key scopes + bootstrap admin

---

## Migration Phases

### Phase 1 — Foundation (Prerequisites)

**Goal**: Wire SDK, fix FastAPI deprecations, add lifecycle events. Zero behaviour change.  
**Risk**: Low  
**AINDY requirement**: Optional (events silently skipped if AINDY not configured)

1. Add `AINDYConfig` to `claw/config/schema.py` and `claw.toml`
2. Create `claw/aindy/__init__.py` and `claw/aindy/client.py`
3. Migrate `@app.on_event` → `lifespan` in `gateway/server.py`
4. Add `FastAPIInstrumentor.instrument_app(app)` in `gateway/server.py`
5. Add fire-and-forget `sys.v1.event.emit` calls at turn start/end in `_run_turn()`
6. Add `claw doctor` check for AINDY connectivity
7. Update test suite: no changes needed to test logic, but add AINDY mock fixture

**Deliverable**: Claw runs identically with or without AINDY. When AINDY is present,
turn lifecycle events appear in `system_events` table.

---

### Phase 2 — Memory Backend

**Goal**: AINDY MAS as primary memory store.  
**Risk**: Medium (memory is on the critical path for every turn)  
**AINDY requirement**: Running instance with Postgres

1. Create `claw/aindy/memory_store.py` implementing `nodus_memory.MemoryStore`
2. Add backend selection in `memory/manager.py`
3. MAS path convention: `/memory/{user_id}/claw/{agent_id}/{node_type}/{node_id}`
4. Wire `"aindy-fallback"` mode: try AINDY, fall back to SQLite on network failure
5. Add `sys.v1.event.emit("claw.memory.written")` inside `AINDYMemoryStore.write()`
6. Update tests: add `memory_backend = "aindy"` test variant with AINDY mock

**Deliverable**: Memory writes go to AINDY MAS. Memory recall uses semantic search
(`sys.v1.memory.search`) with MAS path scoping per agent. `MemorySqliteStore` becomes
the fallback/dev backend.

**Unlock**: causal trace (`sys.v1.memory.trace`), tree walk (`sys.v1.memory.tree`),
cross-agent shared memory via MAS path patterns.

---

### Phase 3 — Execution Tracking + Cron

**Goal**: All Claw execution (turns, cron jobs) visible in AINDY audit layer.  
**Risk**: Low (purely additive observability)  
**AINDY requirement**: Running instance

1. Register `"claw.cron"` job handler with AINDY job registry (if using AINDY APScheduler)
2. Emit `sys.v1.job.submit` from `CronManager` before each turn
3. Add `execution_unit_id` generation per `ConversationalTurn.run()` call
4. Propagate `execution_unit_id` into memory writes (already supported by AINDY MAS node
   `extra.execution_unit_id`)
5. Emit `sys.v1.event.emit("claw.session.started/ended")` from session lifecycle hooks

**Deliverable**: Each Claw turn and cron job has an AINDY `execution_unit_id`. Memory
nodes carry that ID. Full audit trail: event → execution → memory writes.

---

### Phase 4 — Gateway Mount (Optional)

**Goal**: Claw becomes an AINDY application.  
**Risk**: High (requires infrastructure, auth migration, full regression test)  
**AINDY requirement**: Full production instance (Postgres + Redis + OpenAI key for AINDY
internal features)  
**Prerequisite**: Phase 1 lifespan migration must be complete

1. Extract Claw's route handlers from `build_app()` into a standalone `APIRouter`
2. Create `claw/aindy/app_registration.py` — registers Claw router with AINDY `platform_layer.registry`
3. Remove Claw's own uvicorn startup; AINDY's `main.py` becomes the entry point
4. Replace `claw/auth/` with AINDY `require_execution_context` dependency
5. Drop Claw's own health/ready endpoints — use AINDY's `/health` and `/health/sandbox`
6. Update `claw.toml` → `AINDY_AGENT_PLANNER_BACKEND` and env vars for combined startup
7. Delete `claw/auth/` (3 files, ~260 lines)

**Deliverable**: `aindy-runtime` serves `http://host:8000/`. Claw's WebSocket is at
`/apps/claw/ws/chat`. AINDY `/metrics` includes Claw request metrics. AINDY auth
gates all Claw routes. Single process; no SDK HTTP round-trips for memory/events.

---

## Pre-existing Issues Discovered During Audit

These are not introduced by the AINDY integration but should be fixed regardless.

### P1 — FastAPI `on_event` deprecation (live warning in current test run)

**File**: `claw/gateway/server.py:348, 352`  
**Impact**: FastAPI 0.137.1 (now installed) emits `DeprecationWarning` on every test run.
Starlette will remove `on_event` in a future release. Phase 1 mandates this fix.

### P2 — Starlette TestClient httpx warning

**File**: `tests/test_phase4_milestone.py:290`  
**Warning**: `Using httpx with starlette.testclient is deprecated; install httpx2 instead`  
**Fix**: `pip install httpx2` and update the import if/when Starlette removes the httpx shim.
Low urgency — no breakage yet.

### P3 — `BindingResolver` tier comment vs code ordering

**File**: `claw/routing/resolver.py`  
**Note**: Agent-supplied description flags peer weight 70 > peer_channel weight 60 in the
comment, but peer_channel check evaluates first. Verify the intended priority order against
OpenClaw spec. If peer-channel should beat peer, the code order is correct but the comment
weight values are wrong. If peer should beat peer-channel, the `if` block order is inverted.

---

## Decision Log

| Decision | Rationale |
|---|---|
| Claw stays standalone (Phases 1–3) | AINDY requires Postgres + Redis; Claw must remain runnable without infrastructure dependencies |
| `AINDYClient` wrapped with `asyncio.to_thread` | SDK is synchronous; wrapping at one layer is cleaner than per-call `to_thread` in every module |
| Memory fallback stays SQLite, not removed | `memory.backend = "local"` keeps the dev experience zero-infrastructure |
| Events are fire-and-forget | AINDY unavailability must never block a conversational turn |
| Tool definitions stay Anthropic-format | AINDY syscalls serve kernel operations; Anthropic tools serve the LLM tool_use protocol — different contracts |
| Skills stay SKILL.md based | AINDY extension system targets sandboxed plugin code, not prompt-injected capability manifests |
| Phase 4 is explicitly optional | Gateway mount requires full AINDY infrastructure and auth migration; the value is real but the cost is high |
