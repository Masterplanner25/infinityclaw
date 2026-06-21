# OpenClaw → Nodus Migration Plan

> Planning phase deliverable.
> Based on OPENCLAW_TO_NODUS_ANALYSIS.md and OPENCLAW_NODUS_ARCHITECTURE.md.

---

## Guiding Constraints

- **Nodus packages are trusted infrastructure** — never reimplement what a Nodus package provides
- **Channel adapters are isolated** — each adapter is a separate installable package
- **No big bang** — each phase produces a testable artifact
- **WhatsApp is deferred** — highest-risk adapter, addressed in Phase 4 after core is proven
- **Canvas/nodes/voice are out of scope** — native platform integrations deferred indefinitely

---

## What Can Be Implemented Entirely With Nodus

The following require zero or trivial custom code because Nodus packages cover them completely:

| Feature | Nodus package(s) | Notes |
|---|---|---|
| LLM failover (profile rotation, backoff) | `nodus_llm.FailoverClient` + `CredentialStore` | Identical semantics to OpenClaw |
| Agent lifecycle (submit/execute/approve) | `nodus_agent.AgentExecutor` | |
| Capability tokens + guardrails | `nodus_agent` | |
| MCP server + client | `nodus_mcp` | Replaces mcporter, adds server-side |
| Queue with named lanes | `nodus_queue` | Maps directly to OpenClaw lanes |
| Retry policy | `nodus_retry` | |
| Circuit breaker | `nodus_circuit_breaker` | |
| Agent-to-agent messaging | `nodus_a2a` | |
| Approvals workflow | `nodus_approvals` | |
| Governance / risk policy | `nodus_governance` | |
| Observability (OTel, Prometheus, health) | `nodus_observability_framework` | |
| Execution identity (trace_id, session_id) | `std:identity` | |
| EXACTLY_ONCE idempotency | `std:effects` | |
| File system tools | `std:fs` | |
| HTTP client tools | `std:http` | |
| Process execution tools | `std:subprocess` | |
| Retry on tool calls | `std:retry`, `std:circuit_breaker` | |
| Cron expression scheduling | `nodus_sdk.bridges.scheduler` (APScheduler) | |
| Extension registry + manifest | `nodus_extensions` | |
| Sandboxed extensions | `nodus_extension` | |

---

## What Requires Custom Code

Ranked by risk (highest first):

| Feature | Package | Estimated lines | Risk |
|---|---|---|---|
| WhatsApp adapter (Baileys equivalent) | `claw_whatsapp` | 400–800 | High — no Python equivalent of Baileys |
| Browser tool (Playwright CDP) | `claw.tools.browser` | ~800 | Medium — Playwright well-supported |
| Channel adapters (Telegram, Discord, Slack, Signal, Matrix, WebChat) | `claw_*` per channel | ~350 each | Low–Medium per adapter |
| Gateway WS control plane | `claw.gateway` | ~600 | Medium — protocol design |
| System prompt builder | `claw.agents.prompt` | ~200 | Low |
| Memory indexer (Markdown + hybrid search) | `claw.memory` | ~630 | Low — well-defined algorithm |
| Binding resolver (8-tier routing) | `claw.routing` | ~250 | Low — deterministic algorithm |
| Skills loader + injector | `claw.skills` | ~410 | Low |
| Session key scheme + dmScope | `claw.sessions` | ~590 | Low |
| Workspace bootstrapper | `claw.workspace` | ~470 | Low |
| CronManager + delivery | `claw.cron` | ~440 | Low |
| Device pairing store | `claw.auth.device` | ~150 | Low |
| Config schema + loader | `claw.config` | ~200 | Low |

---

## Package Layout

```
C:\dev\claw\
├── claw/                          # Core orchestration package
│   ├── gateway/                   # WS + HTTP control plane
│   ├── agents/                    # Agent runtime wiring
│   ├── sessions/                  # Session key scheme + lifecycle
│   ├── memory/                    # Markdown memory + vector search
│   ├── channels/                  # Adapter registry + DM policy
│   ├── routing/                   # Binding resolver
│   ├── skills/                    # Skills loader + injector
│   ├── cron/                      # CronManager
│   ├── workspace/                 # Bootstrapper + initializer
│   ├── tools/                     # Standard tools + browser
│   ├── auth/                      # Credential + device auth
│   └── config/                    # Config schema + loader
│
├── claw_telegram/                 # Telegram channel adapter
├── claw_discord/                  # Discord channel adapter
├── claw_slack/                    # Slack channel adapter
├── claw_signal/                   # Signal channel adapter
├── claw_matrix/                   # Matrix channel adapter
├── claw_webchat/                  # WebChat adapter (in-process)
├── claw_whatsapp/                 # WhatsApp adapter (high risk, Phase 4)
│
├── workflows/                     # Nodus .nd workflow files
│   ├── memory_flush.nd
│   ├── session_reset.nd
│   ├── heartbeat.nd
│   ├── bootstrap.nd
│   └── boot.nd
│
├── skills/                        # Bundled skills (SKILL.md directories)
├── nodus.toml                     # Project config
└── pyproject.toml                 # Package manifest
```

**Estimated total file count: 80–110 Python files + 5 `.nd` workflows + 6 channel packages**

---

## Phase 1: Research ✅

**Goal**: Understand OpenClaw completely.

**Deliverables**:
- [x] `OPENCLAW_TO_NODUS_ANALYSIS.md` — subsystem-by-subsystem analysis
- [x] `OPENCLAW_NODUS_ARCHITECTURE.md` — system diagram + package responsibilities
- [x] `OPENCLAW_NODUS_MIGRATION_PLAN.md` — this document

**Completed.**

---

## Phase 2: Architecture ✅

**Goal**: Design the Nodus-native successor.

**Deliverables**:
- [x] System diagram (in ARCHITECTURE.md)
- [x] Runtime boundaries (in ARCHITECTURE.md)
- [x] Package responsibilities (in ARCHITECTURE.md)
- [x] Workflow boundaries (in ARCHITECTURE.md)
- [x] Identity, memory, channel, MCP architecture (in ARCHITECTURE.md)

**Completed.**

---

## Phase 3: Foundation

**Goal**: Standing Nodus runtime with one channel, no UI, no browser.
At the end of this phase: a working agent that can receive a message from one channel and reply.

### 3.1 — Project Scaffold

- Initialize `pyproject.toml` with all Nodus ecosystem dependencies
- Create `nodus.toml` (Nodus project config)
- Create `claw/__init__.py`, `claw/config/` (schema + loader)
- Validate Python + venv setup

**Files created: ~10**

### 3.2 — Config Schema

- Define `ClawConfig` Pydantic model matching OpenClaw's `openclaw.json` surface:
  - `gateway.*`, `agents.list[]`, `bindings[]`, `channels.*`, `session.*`, `memory.*`, `skills.*`, `cron.*`
- JSON5 config loader (preserve OpenClaw format for migration)
- Config validation at startup

**Files created: ~6**

### 3.3 — Agent Runtime Wiring

- `claw.agents.registry.AgentRegistry`: loads `agents.list[]`, initializes one `AgentExecutor` per agent
- `claw.agents.prompt.SystemPromptBuilder`: injects workspace files, skills list, tools, time, runtime metadata
- `claw.agents.streaming.BlockStreamer`: 800–1200 char soft split chunker
- `claw.agents.queue.ClawQueue`: lane-aware queue over `nodus_queue` (lanes: `session:<key>`, `main`, `cron`, `subagent`)
- LLM bridge: `nodus_llm.FailoverClient` initialized from config credentials

**Files created: ~8**

### 3.4 — Session Layer

- `claw.sessions.key.SessionKeyBuilder`: generates `agent:<agentId>:<...>` keys per dmScope + chat type
- `claw.sessions.identity.IdentityLinker`: identityLinks cross-channel canonicalization
- `claw.sessions.manager.ClawSessionManager`: wraps `nodus_session.SessionManager` with reset lifecycle
- `claw.sessions.pruner.ContextPruner`: drops old tool results before LLM call
- `claw.sessions.transcript.TranscriptWriter`: persists turns (JSONL or `nodus_store_sql`)
- Session reset workflow: `workflows/session_reset.nd`

**Files created: ~8 Python + 1 `.nd`**

### 3.5 — Workspace + Bootstrap

- `claw.workspace.WorkspaceBootstrapper`: discovers + injects AGENTS.md, SOUL.md, USER.md, etc.
- `claw.workspace.initializer`: `claw setup` — creates default workspace files
- File truncation (20,000 chars per-file, 150,000 chars total)
- Bootstrap workflow: `workflows/bootstrap.nd`

**Files created: ~5 Python + 1 `.nd`**

### 3.6 — Skills

- `claw.skills.loader.SkillLoader`: discovers SKILL.md files from bundled/managed/workspace with precedence
- `claw.skills.gating.SkillGate`: env/config/binary presence checks
- `claw.skills.injector.SkillsInjector`: formats compact system prompt block

**Files created: ~4**

### 3.7 — Standard Tools

- `claw.tools.standard`: register `message`, `sessions_list`, `sessions_send`, `sessions_history`, `sessions_spawn`, `session_status` via `std:tool`
- Tool governance: `nodus_governance.policy` allow/deny enforcement

**Files created: ~3**

### 3.8 — WebChat Adapter (First Channel)

- `claw_webchat.adapter.WebChatAdapter`: FastAPI WebSocket built-in adapter
- WebChat static UI (HTML + JS)
- Inbound receive → routing → agent → outbound send loop

**Files created: ~5**

### 3.9 — Gateway (Minimal)

- `claw.gateway.server`: FastAPI app with WS upgrade
- `claw.gateway.protocol`: `req`/`res`/`event` frame types
- `claw.gateway.auth`: bearer token auth
- `claw.routing.resolver.BindingResolver`: 8-tier binding resolution
- `claw.routing.envelope`: `ClawInboundMessage` + `ClawOutboundMessage`
- `nodus_observability_framework` health + metrics middleware

**Files created: ~7**

### Phase 3 Milestone Test

- `nodus run` starts the gateway
- WebChat browser client connects
- Send a message → agent receives it → calls LLM (Anthropic) → streams reply back
- Session persists across messages
- Skills loaded and visible in `/context`

**Phase 3 total: ~56 files + 2 workflows**

---

## Phase 4: Channels

**Goal**: All non-WhatsApp channels working. WhatsApp planned but deferred.

### 4.1 — Channel Adapter Base

- `claw.channels.base.ClawAdapter`: abstract base wrapping `nodus_adapter_base.Adapter`
- `claw.channels.registry.ChannelAdapterRegistry`: manages adapter lifecycle + health
- `claw.channels.policy.DmPolicyEnforcer`: pairing/allowlist/open enforcement
- `claw.channels.pairing.PairingStore`: SQLite-backed pairing code store

**Files created: ~6**

### 4.2 — Telegram Adapter

- Library: `aiogram` or `python-telegram-bot`
- Features: DM, group/topic, media normalization, retry (Telegram-specific 429 handling), typing indicators

**Files created: ~6**

### 4.3 — Discord Adapter

- Library: `discord.py`
- Features: DM, guild channels, thread isolation, mention gating, reactions

**Files created: ~6**

### 4.4 — Slack Adapter

- Library: `slack-bolt` for Python (official)
- Features: DM, channels, threads, reactions

**Files created: ~6**

### 4.5 — Signal Adapter

- Library: `signal-cli` subprocess bridge
- Features: DM, group messages, media

**Files created: ~5**

### 4.6 — Matrix Adapter

- Library: `matrix-nio`
- Features: DM, rooms, threads

**Files created: ~6**

### 4.7 — WhatsApp Planning

- Decision point: subprocess bridge to Node.js Baileys process vs. Meta Cloud API
- Build the IPC protocol between Python gateway and Node.js Baileys subprocess
- This is a separate work item; may require a Node.js companion process that the Python gateway spawns
- Estimate: ~800 lines (Python bridge side) + maintaining a Node.js Baileys wrapper

**Recommendation**: Start with Meta Cloud API (official, Python SDK available) for business accounts.
Baileys bridge is a separate track with higher maintenance burden.

### 4.8 — Cron + Scheduling

- `claw.cron.manager.CronManager`: CRUD + APScheduler bridge
- `claw.cron.delivery`: announce / webhook / none delivery modes
- Per-job isolated session minting
- Heartbeat workflow: `workflows/heartbeat.nd`
- Boot workflow: `workflows/boot.nd`

**Files created: ~6 Python + 2 `.nd`**

### 4.9 — Multi-Agent Routing

- Full `BindingResolver` with all 8 tiers (peer > parentPeer > guildId+roles > guildId > teamId > accountId > channel > default)
- Per-agent tool policy enforcement via `nodus_governance`
- Per-agent `CredentialStore` isolation
- `openclaw agents add` equivalent CLI command

**Files created: ~5**

### Phase 4 Milestone Test

- Telegram: send DM → agent replies; group mention → agent replies
- Discord: DM + guild channel + threads
- Slack: DM + channel + thread
- Multi-agent: two agents on separate Telegram bots, correct routing
- Cron: morning heartbeat fires, delivers result back

**Phase 4 total: ~46 files + 2 workflows**

---

## Phase 5: Memory & Identity

**Goal**: Full memory subsystem working. Auth profile rotation confirmed.

### 5.1 — Memory Manager

- `claw.memory.manager.MemoryManager`: orchestrates document memory layer
- `claw.memory.chunker.MarkdownChunker`: 400-token chunks, 80-token overlap
- `claw.memory.search.HybridSearcher`: BM25+vector merge, MMR, temporal decay
- `claw.memory.tools`: register `memory_search`, `memory_get` via `std:tool`
- SQLite index: `nodus_store_sql` (aiosqlite-backed)
- Embedding: `nodus_memory.embedding` (local or remote)

**Files created: ~8**

### 5.2 — Pre-Compaction Memory Flush

- Memory flush workflow: `workflows/memory_flush.nd`
- Trigger: session token estimate crosses threshold
- Silent turn: sends system prompt reminder, expects NO_REPLY

**Files created: 1 `.nd`**

### 5.3 — Auth + Device Identity

- `claw.auth.profiles.CredentialStoreManager`: loads `nodus_llm.CredentialStore` from config per agent
- `claw.auth.device.DevicePairingManager`: device token issuance, approval store
- `claw.gateway.pairing`: pairing handshake in WS connect handler

**Files created: ~5**

### 5.4 — Identity Links

- `claw.sessions.identity.IdentityLinker`: reads `session.identityLinks` from config
- Cross-channel peer canonicalization applied in `SessionKeyBuilder`

**Files created: ~2**

### 5.5 — Session Pruning + Compaction

- `claw.sessions.pruner.ContextPruner`: removes tool results older than threshold from in-memory context
- Does NOT rewrite JSONL (same invariant as OpenClaw)
- Token estimation: uses `nodus_llm.would_overflow()` for context window checks

**Files created: ~3**

### Phase 5 Milestone Test

- Write a memory note → `memory_search` finds it semantically
- Daily memory log written → indexed → searchable
- Pre-compaction flush fires on large sessions
- Auth profile rotation: rate limit hit → backoff → rotate → recover
- Cross-channel identityLinks: same person on Telegram and Discord shares a DM session

**Phase 5 total: ~18 files + 1 workflow**

---

## Phase 6: Production Readiness

**Goal**: Deployable, observable, documented system.

### 6.1 — Observability

- OpenTelemetry tracing: `nodus_observability_framework.bootstrap`
- Prometheus metrics: `nodus_observability_framework.metrics`
- Structured JSON logging: `nodus_observability` + `python-json-logger`
- Health endpoint: `nodus_observability_framework.health`
- FastAPI instrumentation: `nodus_observability_framework.fastapi`

**Files created: ~3**

### 6.2 — Security Hardening

- DM policy audit command (`claw security audit`)
- Origin checking for WS connections
- Rate limiting: `nodus_circuit_breaker` per-sender
- Inbound message sanitization (untrusted input path)
- `nodus_approvals` for exec approval gating

**Files created: ~5**

### 6.3 — CLI

- `claw` CLI entry point (Python, mirrors OpenClaw CLI surface)
- Commands: `claw gateway`, `claw agent`, `claw sessions`, `claw channels`, `claw cron`, `claw setup`, `claw doctor`
- `claw doctor`: config validation, channel health probe, workspace check

**Files created: ~8**

### 6.4 — Browser Tool (Playwright)

- `claw.tools.browser.PlaywrightBrowser`: CDP browser tool via Playwright Python
- Screenshot, snapshot, actions, navigation
- Headless Chromium managed by Playwright (not a separate process to manage)

**Files created: ~6**

### 6.5 — Control UI (WebChat + Control Plane)

- Enhance WebChat adapter with control UI
- Sessions list, agent status, config display
- Canvas placeholder (static placeholder, deferred)

**Files created: ~4**

### 6.6 — Daemon / Service

- `systemd` user service unit file
- `launchd` plist for macOS
- `claw gateway --install-daemon` command

**Files created: ~4**

### 6.7 — Testing Infrastructure

- `std:test` integration tests in `.nd` for workflow correctness
- `pytest` integration tests for Python modules
- Mock channel adapter for tests (in-process loopback)
- Live tests for each channel adapter (gated by env vars)

**Files created: ~10**

### Phase 6 Milestone Test

- `claw gateway --install-daemon` installs and starts the service
- Prometheus metrics visible at `:9090`
- `claw doctor` surfaces all config issues
- Browser tool: agent can screenshot a webpage
- Full e2e: WhatsApp message → agent → browser → screenshot → reply (sans WhatsApp pending Phase 4.7)

**Phase 6 total: ~40 files**

---

## Total Estimates

| Phase | Description | Files | Custom lines |
|---|---|---|---|
| Phase 1 | Research | 3 docs | 0 |
| Phase 2 | Architecture | 3 docs | 0 |
| Phase 3 | Foundation | ~56 + 2 workflows | ~3,200 |
| Phase 4 | Channels | ~46 + 2 workflows | ~2,800 |
| Phase 5 | Memory & Identity | ~18 + 1 workflow | ~1,400 |
| Phase 6 | Production Readiness | ~40 | ~1,600 |
| **Total** | | **~160–170 files + 5 workflows** | **~9,000 lines** |

WhatsApp adapter (deferred, Phase 4.7): +800 lines, +8 files if built.
Browser tool (Phase 6.4): ~800 lines already included above.

---

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| WhatsApp: no Python Baileys equivalent | High | Start with Meta Cloud API (business); build Baileys subprocess bridge separately |
| Channel library churn (Telegram/Discord breaking changes) | Medium | Pin library versions; adapter pattern isolates breakage |
| Nodus VM embedding in long-running process | Medium | `NodusRuntime` is designed for this; test for memory leaks in gateway loop |
| `nodus_memory` embedding model download on first run | Low | Pre-download in `claw setup`; use remote embeddings by default |
| SQLite contention under multi-agent concurrent load | Low | Use `aiosqlite` async driver; per-agent SQLite files avoid cross-agent contention |
| Config schema drift (OpenClaw JSON5 vs Nodus TOML) | Low | Support both formats in config loader; migrate users gradually |

---

## Decision Log

These decisions were made during planning and should not be relitigated without new evidence:

1. **Session transcripts**: Preserve JSONL format for compatibility with existing session data. Migrate to `nodus_store_sql` in Phase 3.9 if JSONL proves limiting.

2. **Memory model**: Preserve the Markdown file convention (daily logs + MEMORY.md). This is the key UX differentiator of OpenClaw's memory. Do not replace with pure KV.

3. **Skills**: Preserve SKILL.md format for AgentSkills ecosystem compatibility. Add `.nd` skill support as an additive layer.

4. **WhatsApp**: Defer. Build all other channels first. WhatsApp is a risk item requiring a separate decision.

5. **MCP**: Use `nodus_mcp` directly. Do not port mcporter. This is strictly better.

6. **TypeScript gateway**: Do not port the TypeScript gateway. Start fresh in Python with FastAPI + `nodus_gateway`. The TypeScript version is a reference implementation only.

7. **Canvas/nodes/voice**: Out of scope for this rewrite. These are hardware-specific features that depend on platform companions (macOS app, iOS app). Revisit after core is stable.

8. **Config format**: Support OpenClaw's JSON5 `openclaw.json` format in the config loader so existing users can migrate without rewriting config. Nodus TOML (`nodus.toml`) is the canonical format going forward.
