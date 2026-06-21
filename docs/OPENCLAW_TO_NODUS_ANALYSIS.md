# OpenClaw → Nodus Subsystem Analysis

> Research phase deliverable. Starting from first principles.
> Sources: openclaw_research/, installed Nodus ecosystem (venv/Lib/site-packages/nodus*).

---

## Method

For each OpenClaw subsystem:
1. What problem does it solve?
2. Which Nodus package already solves this?
3. Is custom code required? If so, why?

Coverage tier:
- **Direct** — Nodus already solves this with no or trivial wiring
- **Thin** — Nodus solves the mechanism; custom code adds naming conventions or config only
- **Moderate** — Nodus provides building blocks; a meaningful but bounded adapter is needed
- **Significant** — Nodus has nothing close; this must be built from scratch

---

## 1. Gateway Architecture

### What OpenClaw Does

A single long-lived Node.js/TypeScript daemon bound to `127.0.0.1:18789`.
It is the **control plane** for every subsystem: channels, sessions, agents, cron, config,
tools, canvas, device pairing, HTTP APIs, WebChat, and WebSocket events.

Clients (macOS app, CLI, WebChat, iOS/Android nodes) connect to it over WebSocket.
The Gateway owns all messaging surfaces — only one Gateway process controls a WhatsApp session.
It validates inbound WS frames against TypeBox JSON Schemas, emits typed events
(`agent`, `chat`, `presence`, `health`, `cron`), and maintains a short-lived
idempotency dedupe cache for side-effecting methods.

### Nodus Coverage

| Gateway concern | Nodus package |
|---|---|
| HTTP API surface | FastAPI via `nodus_lang[server]` extras |
| WebSocket control plane | FastAPI WebSocket (`nodus_gateway` client/server gateway) |
| Health / metrics | `nodus_observability_framework` (health, metrics, middleware) |
| Request routing | `nodus_router` |
| Event broadcast | `nodus_events` (event bus) |
| Auth + rate limiting | `nodus_auth`, `nodus_circuit_breaker` |
| Idempotency | `std:effects` (EXACTLY_ONCE) |
| Config reload | `std:fs`, `nodus_extension` host |

### Assessment

**Coverage: Moderate.**

The Nodus packages cover every *concern* of the Gateway but none of them
are pre-wired as a unified control plane.

`nodus_gateway` provides the skeleton (server.py + client.py). `nodus_observability_framework`
provides FastAPI middleware, health checks, and Prometheus. `nodus_events` provides the bus.
`nodus_router` provides binding resolution. `std:effects` handles idempotency.

**Custom code required:** A `claw.gateway` module (~500–800 lines) that:
- Wires these packages into a single FastAPI app with WebSocket upgrade
- Implements the OpenClaw WS wire protocol (`req`/`res`/`event` frame types)
- Manages the connect handshake + challenge signing
- Owns the device pairing store

The raw transport and protocol framing have no Nodus equivalent — that is real custom work.
Everything above the protocol layer (routing, events, health, auth, idempotency) is Nodus-native.

---

## 2. Pi-Agent Architecture

### What OpenClaw Does

An embedded agent runtime derived from pi-mono. The agent:
- Receives a session key, model, and conversation context
- Builds a system prompt (tools, skills, workspace files, time, runtime metadata)
- Calls the LLM in an agentic loop: generate → parse tool calls → execute → repeat
- Supports tool streaming (individual tool results delivered as events) and block streaming (assistant text chunks)
- Serializes runs through a **lane-aware FIFO queue**: one active run per session key, plus a global concurrency cap (`agents.defaults.maxConcurrent`)
- Queue modes: `steer` (inject mid-run), `followup` (queue for next turn), `collect` (coalesce), `steer-backlog`
- Supports `thinking` (extended reasoning) and `verbose` per-session toggles
- Sandboxes execution optionally via Docker (per-session or per-agent scope)

### Nodus Coverage

| Agent concern | Nodus package |
|---|---|
| Agent lifecycle (submit/approve/execute) | `nodus_agent.AgentExecutor` |
| Planning (objective → tool plan) | `nodus_agent.LLMPlanner`, `LocalPlanner` |
| Capability tokens (scoped execution) | `nodus_agent.mint_token()`, `validate_token()` |
| Guardrails (risk policy, duplicate guard) | `nodus_agent.check_risk_policy()`, `DuplicateSubmissionGuard` |
| LLM calls with failover | `nodus_llm.FailoverClient` |
| Queue / concurrency | `nodus_queue` |
| Tool dispatch | `std:tool` |
| Idempotency per run | `std:effects` |
| Streaming events | `nodus_events`, `nodus_channels` |

### Assessment

**Coverage: Thin–Moderate.**

`nodus_agent.AgentExecutor` covers the full agent lifecycle with planning, guardrails,
capability tokens, and approval gating. `nodus_llm.FailoverClient` replaces OpenClaw's
auth profile rotation with identical exponential backoff semantics.

The queue lane system maps cleanly to `nodus_queue` with session-keyed lanes.

**Custom code required:**
- The system prompt builder (injects workspace files, skills list, tools, time, runtime metadata) — OpenClaw-specific UX convention, ~200 lines
- The block streaming chunker (800–1200 char soft splits at paragraph/newline/sentence boundaries) — ~150 lines
- Steer injection (mid-run message injection after tool boundary) — needs a coroutine hook into the executor, ~100 lines
- Session context pruning (drop old tool results before LLM call) — ~100 lines

The agent loop itself is provided by `nodus_agent`. The above are customizations *of* that loop, not replacements.

---

## 3. Session Model

### What OpenClaw Does

- Stable session keys: `agent:<agentId>:<key>` with structured sub-keys per dmScope, group, cron, webhook
- Session store: flat JSON at `~/.openclaw/agents/<agentId>/sessions/sessions.json` (key → metadata)
- Transcripts: JSONL at `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl`
- `dmScope`: controls per-peer isolation (`main`, `per-peer`, `per-channel-peer`, `per-account-channel-peer`)
- `identityLinks`: canonicalizes same-person across channels
- Reset lifecycle: daily (4AM), idle window, manual triggers (`/new`, `/reset`)
- Session pruning: drops old tool results from in-memory prompt; does NOT rewrite JSONL
- Pre-compaction memory flush: silent agentic turn before auto-compaction
- Send policy: per-session allow/deny rules (channel, chatType, keyPrefix)

### Nodus Coverage

| Session concern | Nodus package |
|---|---|
| Session creation + lifecycle | `nodus_session` (entry.py, manager.py) |
| Persistent session store | `nodus_store_sql` (SQLAlchemy ORM) or `aiosqlite` |
| State / checkpoint / resume | `nodus_state` |
| Session-scoped identity | `std:identity` (`session_id()`, `trace_id()`) |
| Approval gating for session ops | `nodus_approvals` |

### Assessment

**Coverage: Thin.**

`nodus_session.SessionManager` handles session entry creation, lookup, and lifecycle management.
`nodus_store_sql` provides the ORM-backed store. `nodus_state` handles resume/checkpoint.

**Custom code required:**
- The structured key scheme (`agent:<agentId>:<channel>:dm:<peerId>` etc.) is a naming convention, not a mechanism. It maps to `nodus_session` keys with a `claw.session.key_builder` helper — ~80 lines.
- `dmScope` logic (per-peer isolation) is a routing rule applied before key construction — ~100 lines.
- `identityLinks` (cross-channel peer canonicalization) requires a lookup table in config, ~60 lines.
- Reset lifecycle (daily + idle + triggers) is a policy applied in `SessionManager`; the APScheduler bridge handles the daily task — ~120 lines.
- JSONL transcript format is unique to OpenClaw; if preserved, it needs a writer/reader — ~150 lines. Alternatively, replace with Nodus's SQL store entirely.

The hardest part (session isolation, concurrency, state persistence) is solved. The naming conventions and reset policies are the custom layer.

---

## 4. Memory Model

### What OpenClaw Does

- **Storage**: Plain Markdown files on disk
  - `memory/YYYY-MM-DD.md` — daily append-only log
  - `MEMORY.md` — curated long-term notes (private sessions only)
- **Indexing**: SQLite-backed vector index + optional BM25 hybrid
  - Per-agent SQLite at `~/.openclaw/memory/<agentId>.sqlite`
  - sqlite-vec extension for vector search acceleration
  - Embedding providers: local (GGUF via node-llama-cpp), OpenAI, Gemini, Voyage, Mistral
- **Recall**: Hybrid BM25 + vector search with MMR re-ranking and temporal decay
- **Tools**: `memory_search`, `memory_get`
- **Pre-compaction flush**: Silent turn reminds model to write to memory before compaction
- **QMD backend** (experimental): external local-first search sidecar

### Nodus Coverage

| Memory concern | Nodus package |
|---|---|
| Shared key-value memory | `std:memory` (`share`, `recall_from`, `recall_all`) |
| Vector memory + embeddings | `nodus_memory` (embedding.py) |
| pgvector backing | `nodus_memory`, `pgvector` installed |
| Native memory engine | `nodus_native_memory_engine` |
| SQL store for index | `nodus_store_sql` |
| File access | `std:fs` |

### Assessment

**Coverage: Moderate.**

`std:memory` provides in-process KV memory. `nodus_memory` provides the vector embedding layer with
the embedding.py interface. The installed `pgvector` package suggests vector search infrastructure exists.

The gap is in the *document* nature of OpenClaw memory: it indexes Markdown files at chunk boundaries,
supports hybrid BM25+vector ranking with MMR and temporal decay. That pipeline is more sophisticated
than a KV store + embedding lookup.

**Custom code required:**
- Markdown chunker (400-token chunks, 80-token overlap) — ~100 lines
- Hybrid search merger (BM25 rank + vector cosine → weighted final score) — ~150 lines
- MMR re-ranker (Jaccard similarity diversity pass) — ~80 lines
- Temporal decay scorer (exponential decay by filename date) — ~60 lines
- `memory_search` tool wrapper (surfaces results to agent) — ~80 lines
- `memory_get` tool wrapper (scoped file read) — ~60 lines
- Daily log rotation (write today's YYYY-MM-DD.md) — ~40 lines

The embedding pipeline and vector store are provided by `nodus_memory`. The Markdown-specific
retrieval features are custom but bounded. Total: ~600 lines for the full memory subsystem.

SQLite is available; pgvector is overkill unless scaling beyond single-user. Start with SQLite.

---

## 5. Identity Model

### What OpenClaw Does

Identity has three layers:
1. **Agent identity**: `agentId` with its own workspace, auth profiles, and session namespace
2. **Channel identity**: DM policies (pairing codes, allowlists), sender E.164/handle per channel
3. **Peer identity**: `identityLinks` canonicalizes same-person across channels; device identity for WS clients (pairing store, device tokens)
4. **Auth profiles**: OAuth tokens + API keys stored in `auth-profiles.json` per agent
5. **Model/provider identity**: profile rotation, cooldowns, per-session stickiness

### Nodus Coverage

| Identity concern | Nodus package |
|---|---|
| Auth tokens (JWT/API keys) | `nodus_auth` (keys.py) |
| Capability tokens (scoped execution) | `nodus_agent.CapabilityToken`, `mint_token()` |
| Trace + session identity propagation | `std:identity` (`trace_id()`, `session_id()`, `execution_unit_id()`) |
| Credential rotation with backoff | `nodus_llm.CredentialStore`, `CredentialProfile` |
| Agent scoping | `nodus_agent.AgentRun` (per-run identity) |
| Governance/policy | `nodus_governance.policy` |

### Assessment

**Coverage: Direct–Thin.**

`nodus_auth` handles JWT/key auth. `nodus_llm.CredentialStore` directly matches OpenClaw's auth
profile rotation: ordered profiles, per-credential exponential backoff (5m→10m→20m→40m→1h),
context window validation. This is **identical** to OpenClaw's model failover design.

`nodus_agent.CapabilityToken` provides scoped execution tokens matching `agents.list[].tools.allow/deny`.

`std:identity` propagates `trace_id()` and `session_id()` automatically — replaces OpenClaw's
`runId` correlation.

**Custom code required:**
- Device pairing store (WS clients declare identity; new devices need approval) — ~150 lines
- DM policy enforcement (pairing/allowlist/open per channel, per sender) — ~120 lines
- `identityLinks` lookup (cross-channel peer canonicalization) — ~80 lines

The auth profile persistence (OAuth token storage) needs a `nodus_auth` wrapper for the
provider-specific OAuth flow, but the credential rotation is covered by `nodus_llm`.

---

## 6. Skills Model

### What OpenClaw Does

Skills are **AgentSkills-compatible directories** containing a `SKILL.md` with YAML frontmatter
and Markdown instructions. They teach the agent how to use tools, not what tools are available.

- Three locations: bundled → managed (`~/.openclaw/skills`) → workspace (highest precedence)
- ClawHub registry (clawhub.com) for community skills
- Skills list injected into system prompt as compact metadata; model reads `SKILL.md` on demand
- Gated by config/env/binary presence
- Plugins can ship their own skills
- Workspace skills override shared skills by name

### Nodus Coverage

| Skills concern | Nodus package |
|---|---|
| Extension registry + manifest | `nodus_extensions` (registry.py, manifest.py) |
| Extension loading + sandboxing | `nodus_extension` (host, worker, capabilities) |
| Tool registration | `std:tool` |
| Runtime discovery | `nodus_extension.registry` |

### Assessment

**Coverage: Moderate.**

`nodus_extensions` provides a registry with manifests, and `nodus_extension` provides a sandboxed
host. These cover the *mechanism* of loading and managing extensions.

But OpenClaw Skills are fundamentally **prompt-engineering artifacts**, not code modules.
A `SKILL.md` is a natural-language instruction document for the LLM, not executable code.
`nodus_extension` is for executable code extensions.

**Custom code required:**
- `claw.skills.SkillLoader`: discovers SKILL.md files from the three locations with precedence rules — ~150 lines
- Skills system prompt injector: formats skills list as compact system prompt block — ~80 lines
- Skills gating evaluator: checks config, env vars, binary presence — ~100 lines
- Skills resolver: handles name collisions across bundled/managed/workspace — ~80 lines

The ClawHub registry integration (clawhub.com) is out of scope for the rewrite (it's an external service).
Skills distribution should use `nodus_extensions` manifests going forward.

**Key design decision**: In the Nodus version, skills become either:
(a) `.nd` files in the `skills/` directory that the agent can import as modules, or
(b) `SKILL.md` prompt files unchanged, loaded by the skills injector above.

Option (b) preserves backward compatibility with AgentSkills ecosystem.
Option (a) makes skills Nodus-native and executable.

Both options can coexist: `.nd` skills are code-executable; `SKILL.md` skills are prompt-only.

---

## 7. Channel Model

### What OpenClaw Does

13+ channel connectors, each a bespoke library integration:
- WhatsApp: Baileys (unofficial WA Web API in Node.js)
- Telegram: grammY
- Slack: Bolt
- Discord: discord.js
- Signal: signal-cli subprocess
- BlueBubbles: REST API (iMessage via macOS)
- iMessage: legacy imsg bridge
- Microsoft Teams: plugin (`@openclaw/msteams`)
- Matrix: plugin (`@openclaw/matrix`)
- Google Chat: Chat API
- WebChat: WS-based browser client
- Zalo, Zalo Personal: plugins

Each channel:
- Implements inbound message receive (text, media, reactions, typing)
- Implements outbound message send (chunked, with retry)
- Handles DM policy (pairing, allowlist, open)
- Manages auth/session credentials
- Reports health/presence

### Nodus Coverage

| Channel concern | Nodus package |
|---|---|
| Adapter protocol (inbound/outbound) | `nodus_adapter_base` (adapter.py, manager.py) |
| Channel primitives | `nodus_channels` |
| Delivery routing | `nodus_delivery` (router.py) |
| Message routing | `nodus_router` (resolver.py) |
| Retry on send | `nodus_retry` |
| Circuit breaker | `nodus_circuit_breaker` |

### Assessment

**Coverage: Significant — this is the largest custom surface.**

`nodus_adapter_base` defines the adapter protocol. Every channel needs a Python adapter that implements
`nodus_adapter_base.Adapter`. The underlying channel libraries are mostly Node.js/TypeScript:
Baileys (WA), grammY (Telegram), discord.js — these have no Python equivalents of equal quality.

**Python alternatives exist but diverge from the TS originals:**
- WhatsApp: `whatsapp-web.py` (unofficial), `pywa` (Cloud API-only)
- Telegram: `python-telegram-bot`, `aiogram` — excellent Python alternatives
- Discord: `discord.py` — solid Python alternative
- Slack: `slack-bolt` for Python — official and complete
- Signal: signal-cli subprocess bridge (language-agnostic)
- Matrix: `matrix-nio` — good Python client
- Google Chat: `google-cloud-pubsub` + Google Chat API — official Python SDK

**Custom code required for each adapter:**
- Base: `claw.channels.base.ClawAdapter` (wraps `nodus_adapter_base.Adapter`) — ~200 lines
- Telegram adapter (python-telegram-bot or aiogram) — ~400 lines
- Discord adapter (discord.py) — ~350 lines
- Slack adapter (slack-bolt Python) — ~350 lines
- Signal adapter (signal-cli subprocess) — ~200 lines
- Matrix adapter (matrix-nio) — ~300 lines
- WebChat adapter (FastAPI WS, built-in) — ~300 lines
- WhatsApp: highest risk — no Python equivalent of Baileys quality. Options:
  - Bridge via subprocess to Node.js Baileys process — ~400 lines (bridge code)
  - Use the official Meta WhatsApp Cloud API — covers business accounts, not personal
  - `whatsapp-web.py` — maintained but less battle-tested than Baileys

Total channel adapters: **~2300–2800 lines** across 7+ adapters. This is the largest custom surface.

`nodus_delivery`, `nodus_router`, `nodus_retry`, `nodus_circuit_breaker` handle everything above
the adapter layer (routing, retry on send, backpressure). The adapter implementations are the gap.

---

## 8. Tool Model

### What OpenClaw Does

Core tools always available (subject to policy):
- `read`, `edit`, `write`, `exec`, `process`, `apply_patch` — filesystem + execution
- `browser` — CDP-controlled Chrome/Chromium
- `message` — send to a session/channel
- `sessions_*` — list, send, history, spawn, status
- `canvas`, `nodes` — platform-specific
- `cron` — schedule jobs
- `memory_search`, `memory_get` — memory tools

Plugins add their own tools via Gateway RPC registration.
Tool policy: per-agent `allow/deny` lists.
`elevated` mode: trusted sender gets elevated access (e.g., exec without approval).

### Nodus Coverage

| Tool concern | Nodus package |
|---|---|
| MCP-compatible tool registry | `std:tool` |
| Tool registration + dispatch | `std:tool`, `nodus_extension` |
| Filesystem tools | `std:fs` |
| HTTP tools | `std:http` |
| Process execution | `std:subprocess` |
| Memory tools | `std:memory` + custom (see §4) |
| Retry on tool calls | `std:retry` |
| Circuit breaker on tools | `std:circuit_breaker` |
| Tool policy / governance | `nodus_governance.policy` |

### Assessment

**Coverage: Direct for standard tools; Significant for browser/canvas/nodes.**

`std:tool` provides the MCP-compatible registry. `std:fs`, `std:subprocess` cover read/write/exec.
`std:retry` and `std:circuit_breaker` cover reliability wrappers.

**Custom code required:**
- `message` tool (send to a session via `nodus_delivery`) — ~100 lines
- `sessions_*` tools (list/send/history/spawn) — ~150 lines
- `cron` tool (schedule via APScheduler bridge) — ~80 lines
- `memory_search`, `memory_get` — covered in §4
- `browser` tool: CDP control of Chrome — **significant** (~800 lines); Playwright (Python) is the recommended approach here as a higher-level CDP wrapper
- `canvas` + `nodes` — platform-specific; out of scope for initial rewrite
- Tool policy enforcement (`nodus_governance.policy`) — thin wrapper, ~100 lines

`std:tool`'s MCP-compatibility means all registered tools are automatically exposed over MCP
via `nodus_mcp` — this is an upgrade over OpenClaw's mcporter bridge.

---

## 9. MCP Integration

### What OpenClaw Does

Via `mcporter` — an external Node.js bridge (`github.com/steipete/mcporter`).
Decoupled from core: add/change MCP servers without restarting the gateway.
OpenClaw deliberately avoids first-class MCP runtime in core.

### Nodus Coverage

`nodus_mcp` — MCP 2026-07-28 RC, bidirectional client + server, bearer-token auth.

### Assessment

**Coverage: Direct. This is an upgrade.**

`nodus_mcp` is first-class MCP, not a bridge. It provides both a server (expose Nodus tools over MCP)
and a client (consume external MCP servers). `std:tool` registers into the MCP-compatible registry.

**Custom code required: None.**

`nodus_mcp` replaces `mcporter` entirely and adds capabilities (server-side MCP). No custom code.
The `.nd` index file in `nodus_mcp/nd/index.nd` provides the runtime integration point.

---

## 10. Scheduling Model

### What OpenClaw Does

Built-in cron scheduler persisted to `~/.openclaw/cron/`.

Job types:
- **Main session**: enqueue a system event; runs on next heartbeat
- **Isolated**: dedicated agent turn in `cron:<jobId>` with delivery (announce/webhook/none)

Features:
- One-shot and recurring (cron expression + tz)
- Wakeup modes: immediate vs next heartbeat
- Webhook delivery per-job
- Delete-after-run option
- Job-level concurrency isolation (runs in `cron` lane)

### Nodus Coverage

| Scheduling concern | Nodus package |
|---|---|
| Cron expression scheduling | APScheduler via `nodus_sdk.bridges.scheduler` |
| Job persistence | `nodus_store_sql` or `nodus_queue` |
| Job delivery (announce/webhook) | `nodus_delivery`, `nodus_events` |
| Isolated session per job | `nodus_session` (fresh session ID) |
| Idempotent job execution | `std:effects` (EXACTLY_ONCE) |
| Job concurrency lane | `nodus_queue` (named lanes) |

### Assessment

**Coverage: Thin.**

APScheduler (installed in venv) + `nodus_sdk.bridges.scheduler` covers cron expression parsing and
firing. `nodus_queue` with a named `cron` lane covers concurrency isolation. `nodus_store_sql`
persists jobs. `std:effects` ensures EXACTLY_ONCE delivery for idempotent job actions.
`nodus_delivery` handles announce (reply-back to channel) vs webhook mode.

**Custom code required:**
- `claw.cron.CronManager`: job CRUD, persistence, and trigger dispatcher — ~300 lines
- Job session minting: creates fresh `cron:<jobId>` session via `nodus_session` — ~60 lines
- Heartbeat integration: main-session jobs inject system events rather than spawning new turns — ~80 lines

The core scheduling mechanism is Nodus-native. The OpenClaw-specific concepts (wakeup modes,
deliver-back, main-session vs isolated distinction) are thin wrappers.

---

## 11. Workspace Model

### What OpenClaw Does

The agent's working directory — the single `cwd` for file tools and context.

Standard files:
- `AGENTS.md` — operating instructions (loaded every session)
- `SOUL.md` — persona + tone
- `USER.md` — user profile
- `IDENTITY.md` — agent name/emoji
- `TOOLS.md` — tool usage notes
- `HEARTBEAT.md` — heartbeat checklist
- `BOOT.md` — startup checklist
- `BOOTSTRAP.md` — one-time first-run ritual
- `memory/YYYY-MM-DD.md` — daily log
- `MEMORY.md` — long-term curated memory
- `skills/` — workspace-specific skills
- `canvas/` — canvas HTML/CSS/JS

Large files are truncated at injection (20,000 chars per-file, 150,000 chars total).
Missing files inject a marker line. Bootstrap files injected only on first turn of session.

### Nodus Coverage

| Workspace concern | Nodus package |
|---|---|
| Filesystem access | `std:fs` |
| Path sandboxing | NodusRuntime `allowed_paths` |
| Memory file management | `std:memory`, `nodus_memory` |
| Extension loading from directory | `nodus_extension` |

### Assessment

**Coverage: Direct — this is a convention, not a mechanism.**

The workspace is just a filesystem directory. `std:fs` covers all file operations. NodusRuntime's
`allowed_paths` (set to workspace CWD by default since v4.0.1) provides sandboxing.

The bootstrap file convention (AGENTS.md, SOUL.md, etc.) is a naming scheme. In a Nodus version,
these become either:
- `.nd` files imported at session start (Nodus-native), or
- Markdown files read by `std:fs` and injected into the system prompt (preserves backward compatibility)

**Custom code required:**
- `claw.workspace.WorkspaceBootstrapper`: discovers and injects bootstrap files into context on first turn — ~200 lines
- File truncation logic (per-file cap + total cap) — ~80 lines
- Missing-file marker injection — ~40 lines
- Workspace initializer (`claw setup` equivalent: creates default files) — ~150 lines

This is mostly conventions expressed as code. No novel mechanism is needed.

---

## 12. Multi-Agent Support

### What OpenClaw Does

Multiple isolated agents in one gateway process:
- `agents.list[]`: each entry has own agentId, workspace, agentDir, session store, auth profiles
- `bindings[]`: route inbound messages to agents by (channel, accountId, peer, guildId, teamId, roles)
- Routing priority: peer > parentPeer > guildId+roles > guildId > teamId > accountId > channel > default
- Per-agent sandbox and tool restrictions (`sandbox.mode`, `tools.allow/deny`)
- Agent-to-agent messaging (opt-in, `tools.agentToAgent.enabled`, allowlisted)
- Skills are per-agent (workspace) or shared (managed)

### Nodus Coverage

| Multi-agent concern | Nodus package |
|---|---|
| Per-agent lifecycle isolation | `nodus_agent` (per-AgentRun scoping) |
| Agent-to-agent communication | `nodus_a2a` (watchdog, coordination) |
| Binding / request routing | `nodus_router` (resolver.py) |
| Session namespace isolation | `nodus_session` (per-agentId keys) |
| Per-agent tool policy | `nodus_governance.policy` |
| Per-agent approvals | `nodus_approvals` |

### Assessment

**Coverage: Direct–Thin.**

`nodus_a2a` directly covers agent-to-agent communication. `nodus_router` handles binding resolution
with configurable match rules. `nodus_session` isolates sessions by agentId naturally.
`nodus_governance.policy` expresses per-agent tool allow/deny.

**Custom code required:**
- `claw.agents.AgentRegistry`: loads `agents.list[]` config and initializes per-agent executors — ~200 lines
- `claw.routing.BindingResolver`: implements the 8-tier most-specific-wins rule from config — ~250 lines
- Auth profile isolation: ensures each agent reads its own `nodus_llm.CredentialStore` — ~80 lines

The binding resolver logic (8 tiers, first-match) is the only meaningful custom algorithm here.
Everything below it (session isolation, A2A, governance) is Nodus-native.

---

## Summary Matrix

| Subsystem | Coverage Tier | Key Nodus Packages | Custom Code Estimate |
|---|---|---|---|
| Gateway (control plane) | Moderate | `nodus_gateway`, `nodus_events`, `nodus_router`, `std:effects` | ~600 lines |
| Pi-Agent Runtime | Thin | `nodus_agent`, `nodus_llm`, `nodus_queue` | ~550 lines |
| Session Model | Thin | `nodus_session`, `nodus_store_sql`, `nodus_state` | ~590 lines |
| Memory Model | Moderate | `nodus_memory`, `nodus_store_sql`, `std:fs` | ~630 lines |
| Identity Model | Direct–Thin | `nodus_auth`, `nodus_llm`, `nodus_agent`, `std:identity` | ~350 lines |
| Skills Model | Moderate | `nodus_extensions`, `std:tool` | ~410 lines |
| Channel Adapters | Significant | `nodus_adapter_base`, `nodus_delivery`, `nodus_retry` | ~2500 lines |
| Tool Model | Direct + Significant (browser) | `std:tool`, `std:fs`, `std:subprocess`, `nodus_governance` | ~1330 lines |
| MCP Integration | **Direct** | `nodus_mcp` | 0 lines |
| Scheduling | Thin | APScheduler bridge, `nodus_queue`, `nodus_store_sql` | ~440 lines |
| Workspace | Direct | `std:fs`, NodusRuntime `allowed_paths` | ~470 lines |
| Multi-Agent | Direct–Thin | `nodus_a2a`, `nodus_router`, `nodus_session`, `nodus_governance` | ~530 lines |

**Estimated total custom code: ~8,400 lines** (across all subsystems, excluding tests and channel adapters at maximum scope)

**Channel adapters alone account for ~30% of total custom code** and represent the highest risk
because the best underlying libraries (Baileys for WhatsApp) are TypeScript-only.

**Nodus covers ~65–70% of the problem domain directly or with thin wrappers.**
The remaining 30–35% is primarily channel connectivity and OpenClaw-specific UX conventions
(workspace file layout, system prompt construction, skills injection).

---

## What Nodus Does NOT Cover (Gaps)

1. **WhatsApp via Baileys** — no Python equivalent of equal quality. Mitigation: subprocess bridge to Node.js Baileys, or Meta Cloud API (business accounts only).
2. **Browser control (CDP)** — Playwright for Python is the recommended replacement. Full feature parity is achievable but ~800 lines.
3. **Canvas + iOS/Android nodes** — native platform integrations. Out of scope for the core rewrite.
4. **Voice Wake + Talk Mode (ElevenLabs)** — TTS/STT integration. `nodus_sdk` has no audio bridge today. Would need a custom `claw.voice` module.
5. **ClawHub registry** — community skills distribution. Out of scope for the rewrite; replaced by `nodus_extensions` manifests.
6. **Tailscale auto-configuration** — gateway tunnel management. Easy subprocess call; ~100 lines.
