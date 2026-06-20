# Architecture — Infinity Claw

## Overview

Infinity Claw is organized in layers. Each layer has a single responsibility and communicates with adjacent layers through well-defined interfaces.

```
User / External System
        ↓
  Channel Adapters
        ↓
    Gateway (FastAPI + WebSocket)
        ↓
  Agent Runtime (Nodus + AINDY)
        ↓
  Knowledge Layer  ←──────────────────── [Phase 5+]
        ↓
  Memory / Workspace / Tools
        ↓
  AINDY Execution Kernel
```

---

## Subsystems

### Channel Adapters

Translate external protocol messages (Telegram, Discord, Slack, Matrix, Signal, WebChat WS) into a uniform `InboundEnvelope` and route it to the gateway. Each adapter is an independent package (`claw_telegram`, `claw_discord`, etc.) registered against the `ChannelAdapterRegistry`.

**Boundary:** Adapters know nothing about agents. They produce envelopes and consume text responses.

---

### Gateway (`claw/gateway/server.py`)

The gateway is the coordination hub. It owns:

- `AgentRegistry` — one `ConversationalTurn` per agent, credential store, model config
- `ClawSessionManager` — asyncio lock per session key; LLM-based compaction + message pruning
- `ChannelAdapterRegistry` — inbound/outbound adapter dispatch
- `BindingResolver` — channel + peer → agent_id routing
- `SkillLoader` / `SkillGate` — file-based skills with allow/deny
- `MemoryManager` — SQLite or AINDY MAS memory + recall injection
- `KnowledgeIndex` / `KnowledgeRetriever` / `KnowledgeInjector` — FTS5 workspace knowledge (optional, Phase 5)
- `ToolRegistry` — shared tool definitions; `scoped_executor` injects `agent_id` per turn
- `CronManager` — APScheduler-backed cron jobs
- `AuthManager` — JWT issuance + `SqliteApiKeyStore`
- `_AsyncAINDYClient` — optional async bridge to AINDY runtime

**Boundary:** The gateway serializes concurrent messages to the same session (one asyncio lock per key). It does not know the content of conversations — only their structure.

---

### Agent Runtime

Each agent is a `ConversationalTurn` (Nodus-managed) wrapping a direct `anthropic.AsyncAnthropic` streaming call. Agents are isolated: separate credential stores, workspace directories, and memory namespaces.

**Turn pipeline:**

```
1. Detect is_new_session (before appending user message)
2. Load workspace files + skills + recall memories + retrieve knowledge chunks
3. Build system prompt (PromptContext: identity → runtime → boot → memories → knowledge → skills)
4. Append user message; compact if needed; prune
5. Fire AINDY session.started (if new) + turn.start events (fire-and-forget)
6. turn.run() → stream chunks to channel
7. Append assistant response
8. Fire AINDY turn.complete / turn.error event
```

Each turn carries an `execution_unit_id` (UUID) that threads through memory writes, AINDY events, and cron jobs — forming a complete audit trail.

---

### Knowledge Layer *(Phase 5 — complete)*

The knowledge layer sits between the agent runtime and raw workspace files. It indexes non-identity workspace content and retrieves only what is relevant to the current turn — preventing context window pressure as workspaces grow.

```
File / Asset (non-identity, supported extension)
    ↓
WorkspaceScanner  ← excludes AGENTS.md, SOUL.md, etc.
    ↓
ingest_file()     ← parse_file() + chunk_text() (sliding window, configurable size/overlap)
    ↓
KnowledgeIndex    ← SQLite FTS5: knowledge_chunks (metadata) + knowledge_fts (BM25 index)
    ↓
KnowledgeRetriever.retrieve()  ← async, OR-joined FTS5 query, top-K by BM25 rank
    ↓
KnowledgeInjector.build_block()  ← ## Relevant Knowledge section in system prompt
```

Identity/boot files (AGENTS.md, SOUL.md, IDENTITY.md, USER.md, TOOLS.md, HEARTBEAT.md, BOOT.md, BOOTSTRAP.md) remain verbatim-injected by `WorkspaceBootstrapper`. The knowledge layer covers everything else.

Enabled via `[knowledge] enabled = true` in `claw.toml`. Startup scan indexes all agents' workspaces on `ClawGateway.startup()`. On-demand reindex: `claw workspace index [--agent ID]`.

---

### Memory

Two storage backends, selectable per deployment:

| Backend | Config | Use case |
|---|---|---|
| `local` | `[memory] backend = "sqlite"` | Self-contained, no AINDY required |
| `aindy` | `[aindy] memory_backend = "aindy"` | AINDY MAS (Postgres + pgvector); shared across Weave nodes |
| `aindy-fallback` | `[aindy] memory_backend = "aindy-fallback"` | AINDY with automatic SQLite fallback on connectivity failure |

Memory is per-agent namespaced. The LLM sees recalled memories injected into the system prompt; it never sees or sets `agent_id` directly.

---

### Tools

Tools are registered on a shared `ToolRegistry` and scoped at call time. The `scoped_executor` injects `agent_id` before dispatching, so tool handlers never receive routing information from the LLM.

Built-in tools: `remember`, `recall`, `list_memories`, `forget`, `browser_fetch`.

Skills extend the tool surface through file-based `.skill` definitions with allow/deny gating per agent.

---

### AINDY Execution Kernel

AINDY is the optional execution kernel. It provides:

- **Event bus** (Redis-backed): turn lifecycle events, memory write events, cron execution events
- **MAS memory** (Postgres + pgvector): distributed, searchable, shared memory across the Weave
- **Syscall dispatcher**: 10-step pipeline; 17 built-in syscalls; never raises
- **Platform layer**: mounts Claw's `APIRouter` inside a larger AINDY deployment

AINDY is always optional. Three concentric guards prevent AINDY unavailability from blocking a turn:

1. `self._aindy is None` — client not constructed
2. `if self._aindy and config.aindy.emit_events:` — gated at each call site
3. `except Exception: pass` — fire-and-forget; failures are logged, not raised

---

## Data Flow (full request)

```
User → Telegram
    → TelegramAdapter.handle_message()
    → InboundEnvelope(channel="telegram", peer_id="123", text="...")
    → ClawGateway.handle_inbound()
    → BindingResolver.resolve() → agent_id="main"
    → session_key = "telegram:main:123"
    → async with session_lock[session_key]:
        → MemoryManager.recall()
        → KnowledgeRetriever.retrieve()  (if knowledge enabled)
        → SkillsInjector.inject()
        → PromptContext.build()
        → ConversationalTurn.run()
            → anthropic.messages.stream()
            → [tool calls → ToolRegistry.invoke()]
        → MemoryManager.remember() [if LLM triggered]
        → TelegramAdapter.send_message(response)
    → AINDY turn.complete event (fire-and-forget)
```

---

## Deployment Modes

### Standalone

```bash
claw start   # FastAPI on http://127.0.0.1:18789/
```

Full app with `/health`, `/ready`, observability, and all Claw routes.

### Mounted (AINDY Platform Layer)

```python
from claw.aindy.app_registration import register_claw_app
gateway = await register_claw_app(prefix="/claw")
```

Claw routes mounted inside a larger AINDY FastAPI app. Health and observability provided by the platform layer. `GatewayAuth` in bypass mode — AINDY has already authenticated the request.

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI + Starlette + WebSocket |
| LLM client | `anthropic.AsyncAnthropic` (streaming) |
| Orchestration DSL | Nodus Language 4.0.5 (29-package runtime) |
| Execution kernel | AINDY runtime 1.4.0 |
| Scheduling | APScheduler |
| Memory (local) | SQLite (`sqlite3`) |
| Memory (cloud) | AINDY MAS (Postgres + pgvector) |
| Auth | JWT + persistent API key store |
| Observability | OpenTelemetry via `nodus-observability-framework` |
| Config | TOML + Pydantic |
