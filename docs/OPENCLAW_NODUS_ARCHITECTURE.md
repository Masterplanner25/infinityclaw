# OpenClaw Nodus Architecture

> Architecture phase deliverable. Assumes Nodus is the primary platform.
> Based on analysis in OPENCLAW_TO_NODUS_ANALYSIS.md.

---

## Design Principles

1. **Reuse Nodus packages first.** Custom code only where no Nodus equivalent exists.
2. **Minimize the control plane.** OpenClaw's TypeScript gateway was a control plane *and* an orchestration engine. In the Nodus version, orchestration is Nodus-native — the gateway becomes thin.
3. **Channels are adapters, not core.** Channel connectors implement `nodus_adapter_base.Adapter`. The core does not know about WhatsApp or Telegram.
4. **Workflows over code.** Session reset, memory flush, heartbeat, and cron are Nodus workflows — not imperative TypeScript handlers.
5. **MCP is first-class.** Every tool registered with `std:tool` is automatically exposed over MCP via `nodus_mcp`. No bridge needed.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CHANNEL LAYER                             │
│                                                                   │
│  [WhatsApp]  [Telegram]  [Discord]  [Slack]  [Signal]  [Matrix] │
│  [WebChat]   [Google Chat]   [Zalo]   [Teams]   [BlueBubbles]   │
│       │            │           │         │          │            │
│       └────────────┴───────────┴─────────┴──────────┘            │
│                          │ nodus_adapter_base.Adapter             │
└──────────────────────────┼──────────────────────────────────────┘
                           │ inbound envelope
┌──────────────────────────▼──────────────────────────────────────┐
│                     CLAW GATEWAY                                  │
│                                                                   │
│  FastAPI + WebSocket (nodus_gateway + nodus_observability_fw)    │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐ │
│  │  Binding    │  │   Device    │  │    Control UI / WebChat  │ │
│  │  Resolver   │  │   Pairing   │  │    (static + WS client)  │ │
│  │(nodus_router)│  │  (claw.auth)│  │                          │ │
│  └──────┬──────┘  └─────────────┘  └──────────────────────────┘ │
│         │ agentId                                                  │
└─────────┼───────────────────────────────────────────────────────┘
          │ routed to agent
┌─────────▼───────────────────────────────────────────────────────┐
│                     AGENT RUNTIME LAYER                           │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              nodus_agent.AgentExecutor                   │    │
│  │                                                           │    │
│  │  PlannerBackend   GuardrailViolation   CapabilityToken   │    │
│  │  LLMPlanner       DuplicateGuard       check_risk_policy │    │
│  └───────────────────────┬───────────────────────────────────┘    │
│                          │                                         │
│  ┌────────────────────── │ ──────────────────────────────────┐   │
│  │  nodus_llm.FailoverClient                                  │   │
│  │  CredentialStore  CredentialProfile  (Anthropic/OpenAI)   │   │
│  └───────────────────────┴───────────────────────────────────┘    │
│                                                                   │
│  Queue: nodus_queue (lanes: session:<key>, main, cron, subagent) │
│  Events: nodus_events (agent, chat, presence, cron, health)      │
└─────────────────────────────────────────────────────────────────┘
          │ tool calls
┌─────────▼───────────────────────────────────────────────────────┐
│                        TOOL LAYER                                 │
│                                                                   │
│  std:tool (MCP-compatible registry)                              │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐  │
│  │ std:fs   │ │std:http  │ │std:subpr.│ │  nodus_mcp server  │  │
│  │read/write│ │get/post  │ │exec/spawn│ │  (exposes all tools│  │
│  └──────────┘ └──────────┘ └──────────┘ │  over MCP protocol)│  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ └───────────────────┘  │
│  │ message  │ │ sessions │ │  cron    │                          │
│  │  (send)  │ │ (list/   │ │(schedule)│                          │
│  └──────────┘ │ spawn)   │ └──────────┘                          │
│               └──────────┘                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  browser (Playwright CDP)   canvas   memory_search/get   │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
          │ tool governance
┌─────────▼───────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                           │
│                                                                   │
│  Sessions:     nodus_session + nodus_state + nodus_store_sql     │
│  Memory:       nodus_memory (embeddings) + std:memory (KV)       │
│  Auth:         nodus_auth + nodus_llm.CredentialStore            │
│  Scheduling:   APScheduler bridge (nodus_sdk.bridges.scheduler)  │
│  Delivery:     nodus_delivery + nodus_router                     │
│  Resilience:   nodus_retry + nodus_circuit_breaker               │
│  Governance:   nodus_governance + nodus_approvals                 │
│  A2A:          nodus_a2a (agent-to-agent, opt-in)                │
│  Observability:nodus_observability_framework (OTel, Prometheus)  │
│  Extensions:   nodus_extensions + nodus_extension                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Runtime Boundaries

### Boundary 1: Gateway ↔ Agent

The Gateway is responsible for:
- Receiving inbound channel messages and mapping them to `(agentId, sessionKey, envelope)`
- Routing to the correct `AgentExecutor` via the binding resolver
- Maintaining WS client connections (macOS app, CLI, WebChat)
- Device pairing and auth
- Cron job management

The Agent is responsible for:
- Everything inside a single agent turn: LLM calls, tool execution, streaming
- Session state (transcript, pruning, compaction)
- Memory read/write

The Gateway does NOT reach into agent sessions. The Agent does NOT know about channels.
The boundary is the `ClawEnvelope` struct passed from Gateway to Agent.

### Boundary 2: Channel Adapters ↔ Gateway

Channel adapters are **external processes or in-process modules** implementing `nodus_adapter_base.Adapter`.
They:
- Connect to their upstream provider (Telegram servers, Discord gateway, etc.)
- Normalize inbound messages to `ClawInboundMessage` (channel, accountId, peerId, chatType, text, media)
- Accept outbound sends (text, media, reaction, typing indicator)
- Report health to the Gateway's channel health monitor

The Gateway does NOT import Baileys, grammY, discord.js, or any channel library directly.
Adapters are the only code that touches external messaging APIs.

### Boundary 3: Tools ↔ Agent Runtime

Tools are registered in `std:tool` by name. The `AgentExecutor` dispatches tool calls by name.
Tools do not call back into the agent — they are pure functions: input → output.
The `message` tool is the only exception: it dispatches outbound sends via `nodus_delivery`,
which routes to the appropriate channel adapter.

### Boundary 4: Nodus Runtime ↔ Python Host

The Nodus `.nd` language runtime (the VM) is embedded via Python. Workflows and scheduled
tasks are expressed as `.nd` files executed by `NodusRuntime`. Python infrastructure packages
(`nodus_agent`, `nodus_llm`, etc.) are the host. The host exposes capabilities to `.nd` scripts
via `std:tool` registrations and `std:sys` syscalls.

---

## Package Responsibilities

### `claw` (core orchestration package)

The main Python package. Thin orchestration layer over Nodus packages.

```
claw/
  gateway/
    server.py          # FastAPI + WebSocket server
    protocol.py        # WS frame types (req/res/event)
    pairing.py         # device pairing store
    client.py          # CLI/macOS WS client
  agents/
    registry.py        # AgentRegistry: loads agents.list[]
    executor.py        # wraps nodus_agent.AgentExecutor
    prompt.py          # system prompt builder (workspace files, skills, tools, time)
    streaming.py       # block streaming chunker (800-1200 char soft splits)
    queue.py           # lane-aware queue bridge over nodus_queue
  sessions/
    key.py             # session key scheme: agent:<agentId>:<channel>:...
    manager.py         # wraps nodus_session.SessionManager
    dmscope.py         # dmScope rules (main, per-peer, per-channel-peer)
    identity.py        # identityLinks lookup
    pruner.py          # trim old tool results before LLM call
    transcript.py      # JSONL writer/reader (or delegate to nodus_store_sql)
  memory/
    manager.py         # wraps nodus_memory + Markdown chunking
    chunker.py         # 400-token Markdown chunker, 80-token overlap
    search.py          # hybrid BM25+vector search, MMR, temporal decay
    tools.py           # memory_search + memory_get tool registrations
  channels/
    base.py            # ClawAdapter (wraps nodus_adapter_base)
    registry.py        # channel adapter registry + health monitor
    policy.py          # DM policy (pairing/allowlist/open) enforcement
    pairing.py         # pairing code store + approval flow
  routing/
    resolver.py        # BindingResolver: 8-tier most-specific-wins
    envelope.py        # ClawInboundMessage + ClawOutboundMessage
  skills/
    loader.py          # SkillLoader: three-location precedence
    injector.py        # skills system prompt injector
    gating.py          # env/config/binary presence gating
  cron/
    manager.py         # CronManager: CRUD + APScheduler bridge
    delivery.py        # announce / webhook / none delivery modes
  workspace/
    bootstrapper.py    # inject bootstrap files on first turn
    initializer.py     # claw setup: create default files
  tools/
    standard.py        # message, sessions_*, cron tool registrations
    browser.py         # Playwright CDP browser tool (~800 lines)
  auth/
    profiles.py        # wraps nodus_llm.CredentialStore
    device.py          # device pairing + token issuance
  config/
    loader.py          # openclaw.json / nodus.toml config loader
    schema.py          # Pydantic config schema
```

### `claw_telegram`, `claw_discord`, `claw_slack`, `claw_signal`, `claw_matrix`, `claw_webchat` (channel adapter packages)

Each is a separate installable package implementing `ClawAdapter`.

```
claw_telegram/
  adapter.py       # aiogram or python-telegram-bot based ClawAdapter
  media.py         # photo/video/audio normalization
  auth.py          # bot token management

claw_discord/
  adapter.py       # discord.py based ClawAdapter
  intents.py       # required intents setup
  guild.py         # guild/channel routing

claw_slack/
  adapter.py       # slack-bolt Python based ClawAdapter
  events.py        # Slack events API handler

claw_signal/
  adapter.py       # signal-cli subprocess bridge
  process.py       # signal-cli lifecycle manager

claw_matrix/
  adapter.py       # matrix-nio based ClawAdapter

claw_webchat/
  adapter.py       # FastAPI WebSocket based (built into claw.gateway)
  client.html      # static WebChat UI
```

### `.nd` Workflow Files

Nodus `.nd` workflows replace TypeScript event handlers for recurring logic:

```
workflows/
  memory_flush.nd        # pre-compaction silent memory flush turn
  session_reset.nd       # daily/idle session reset
  heartbeat.nd           # heartbeat agent turn
  bootstrap.nd           # first-session workspace file injection
  boot.nd                # BOOT.md startup checklist execution
```

---

## Workflow Boundaries

### What Becomes a Workflow (`.nd`)

| OpenClaw behavior | Nodus workflow | Why |
|---|---|---|
| Pre-compaction memory flush | `memory_flush.nd` | Repeating pattern with conditional trigger + EXACTLY_ONCE |
| Daily session reset (4AM) | `session_reset.nd` | Scheduled, idempotent |
| Heartbeat (HEARTBEAT.md execution) | `heartbeat.nd` | Recurring, isolated turn |
| First-session bootstrap injection | `bootstrap.nd` | One-time per session, conditional |
| BOOT.md startup checklist | `boot.nd` | Once per gateway restart |

### What Stays Imperative Python

| OpenClaw behavior | Why it stays Python |
|---|---|
| WS protocol framing (req/res/event) | Not a workflow; it's a transport protocol |
| Channel adapter inbound receive | Driven by external event loop (aiogram, discord.py) |
| Device pairing flow | Interactive state machine, not a workflow |
| Binding resolution (8-tier match) | Pure function, no async |
| Config loading + validation | One-time startup, not recurring |

---

## Identity Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Identity Layers                      │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Agent Identity                                   │ │
│  │  agentId → workspace + agentDir + session ns    │ │
│  │  Managed by: claw.agents.AgentRegistry           │ │
│  └─────────────────────────────────────────────────┘ │
│                        │                              │
│  ┌─────────────────────▼───────────────────────────┐ │
│  │ Auth / Credential Identity                       │ │
│  │  nodus_llm.CredentialStore per agent             │ │
│  │  CredentialProfile: api_key or OAuth             │ │
│  │  Backoff: 5m→10m→20m→40m→1h (same as OpenClaw)  │ │
│  └─────────────────────────────────────────────────┘ │
│                        │                              │
│  ┌─────────────────────▼───────────────────────────┐ │
│  │ Peer / Channel Identity                          │ │
│  │  inbound: (channel, accountId, peerId, chatType) │ │
│  │  dmScope: maps peerId → sessionKey               │ │
│  │  identityLinks: canonicalize across channels     │ │
│  │  Managed by: claw.sessions.identity              │ │
│  └─────────────────────────────────────────────────┘ │
│                        │                              │
│  ┌─────────────────────▼───────────────────────────┐ │
│  │ Device / Client Identity                         │ │
│  │  WS clients declare device identity on connect  │ │
│  │  New devices: pairing code flow                  │ │
│  │  Approved: device token issued by nodus_auth     │ │
│  │  Managed by: claw.gateway.pairing                │ │
│  └─────────────────────────────────────────────────┘ │
│                        │                              │
│  ┌─────────────────────▼───────────────────────────┐ │
│  │ Execution Identity (Nodus-native)                │ │
│  │  std:identity: trace_id, session_id, exec_unit   │ │
│  │  nodus_agent.CapabilityToken per run             │ │
│  │  std:effects: EXACTLY_ONCE action_id             │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## Memory Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   Memory Architecture                     │
│                                                           │
│  Two memory paradigms coexist:                           │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Document Memory (OpenClaw convention, preserved)  │   │
│  │                                                     │   │
│  │  memory/YYYY-MM-DD.md  (daily append-only log)    │   │
│  │  MEMORY.md             (curated long-term)         │   │
│  │                                                     │   │
│  │  Indexed by: claw.memory.Manager                   │   │
│  │  Engine: nodus_memory.embedding                    │   │
│  │  Store: SQLite (nodus_store_sql / aiosqlite)       │   │
│  │  Search: Hybrid BM25+vector, MMR, temporal decay   │   │
│  │  Tools: memory_search, memory_get → std:tool       │   │
│  └───────────────────────────────────────────────────┘   │
│                            │                              │
│  ┌─────────────────────────▼─────────────────────────┐   │
│  │  KV Memory (Nodus-native, new)                     │   │
│  │                                                     │   │
│  │  std:memory: share(ns, key, val), recall_from      │   │
│  │  Namespaces: agent:<id>, session:<key>, global     │   │
│  │  Use for: runtime state, tool results, flags       │   │
│  │  Not for: durable notes (use Markdown layer above) │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  Separation rule:                                         │
│  • Agent writes a note to remember → Markdown layer       │
│  • Code needs to store/retrieve state → KV layer          │
└──────────────────────────────────────────────────────────┘
```

---

## Channel Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Channel Architecture                           │
│                                                                   │
│  Each channel adapter:                                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  External Provider     Channel Adapter      Claw Gateway   │ │
│  │                                                             │ │
│  │  [Telegram servers] → [claw_telegram      ] → inbound evt  │ │
│  │  [Discord gateway ] → [claw_discord       ] → inbound evt  │ │
│  │  [Slack events API] → [claw_slack         ] → inbound evt  │ │
│  │  [Signal CLI proc ] → [claw_signal        ] → inbound evt  │ │
│  │  [Matrix server   ] → [claw_matrix        ] → inbound evt  │ │
│  │  [Browser WS      ] → [claw_webchat       ] → inbound evt  │ │
│  │  [WhatsApp (*)    ] → [claw_whatsapp      ] → inbound evt  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  (*) WhatsApp: subprocess bridge to Node.js Baileys process,     │
│      or Meta Cloud API for business accounts.                     │
│      Highest-risk adapter — plan separately.                      │
│                                                                   │
│  Adapter interface (nodus_adapter_base):                         │
│    connect() → None                                               │
│    disconnect() → None                                            │
│    receive() → AsyncIterator[ClawInboundMessage]                 │
│    send(msg: ClawOutboundMessage) → None                         │
│    health() → AdapterHealth                                       │
│                                                                   │
│  DM Policy (claw.channels.policy):                               │
│    pairing  → unknown senders get code, no processing            │
│    allowlist → only allowlisted senders processed                │
│    open     → all senders processed (requires explicit opt-in)   │
│                                                                   │
│  Security: DM policy evaluated BEFORE routing to agent.          │
│  Pairing codes stored in claw.channels.pairing (SQLite).         │
└─────────────────────────────────────────────────────────────────┘
```

---

## MCP Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Architecture                             │
│                                                                   │
│  Tool registration (std:tool):                                   │
│    All tools registered here are auto-exposed over MCP           │
│                                                                   │
│  ┌───────────────────────┐    ┌──────────────────────────────┐  │
│  │   Internal tools      │    │   External MCP servers       │  │
│  │   (claw.tools.*)      │    │   (any MCP-compatible tool)  │  │
│  │   + std:fs/http/etc   │    │                              │  │
│  └───────────┬───────────┘    └─────────────────┬────────────┘  │
│              │                                   │               │
│              ▼                                   ▼               │
│         std:tool registry                   nodus_mcp.client     │
│              │                                   │               │
│              └──────────────┬────────────────────┘               │
│                             │                                     │
│                    nodus_mcp.server                               │
│                  (MCP 2026-07-28 RC)                             │
│                  bidirectional, bearer auth                       │
│                             │                                     │
│                     External MCP clients                          │
│                  (Claude Code, other tools)                       │
│                                                                   │
│  No mcporter needed. No bridge process. First-class MCP.         │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Remains OpenClaw-Specific

These concepts are preserved in the Nodus version but express as Claw-specific conventions:

| Concept | Form in Nodus version |
|---|---|
| Workspace bootstrap files (AGENTS.md, SOUL.md, etc.) | Markdown files read by `claw.workspace.WorkspaceBootstrapper`, injected into system prompt |
| Skills (SKILL.md instruction documents) | Preserved as-is; `claw.skills.SkillLoader` handles discovery and injection |
| AgentSkills compatibility | Preserved; workspace `.nd` skills are additive, not replacing |
| DM pairing security model | `claw.channels.pairing` — unique OpenClaw security feature, retained |
| identityLinks cross-channel canonicalization | `claw.sessions.identity` — unique feature, retained |
| Session key naming scheme | `claw.sessions.key` — naming convention over `nodus_session` |
| Block streaming chunker | `claw.agents.streaming` — UX feature, retained |
| Daily session reset (4AM) | `workflows/session_reset.nd` — Nodus workflow |

## What Becomes Nodus-Native

These OpenClaw concepts are replaced by Nodus primitives:

| OpenClaw concept | Nodus replacement |
|---|---|
| Custom auth profile rotation | `nodus_llm.CredentialStore` + `CredentialProfile` |
| Custom model failover | `nodus_llm.FailoverClient` |
| Custom queue/lane system | `nodus_queue` (named lanes) |
| Custom retry policy | `nodus_retry` |
| Custom circuit breaker | `nodus_circuit_breaker` |
| Custom cron scheduler | APScheduler bridge (`nodus_sdk.bridges.scheduler`) |
| Custom observability | `nodus_observability_framework` (OTel, Prometheus, health) |
| mcporter MCP bridge | `nodus_mcp` (first-class, bidirectional) |
| Agent-to-agent (opt-in) | `nodus_a2a` |
| Approvals / exec approval manager | `nodus_approvals` |
| Risk policy checks | `nodus_governance` |
| Capability tokens per run | `nodus_agent.CapabilityToken` |
| Idempotency keys (send, agent methods) | `std:effects` EXACTLY_ONCE |
| Execution trace/run correlation | `std:identity` (`trace_id`, `session_id`) |

## What Disappears Entirely

These OpenClaw concepts have no analog and are not needed:

| OpenClaw concept | Why it disappears |
|---|---|
| TypeScript WS daemon | Replaced by Python FastAPI + WebSocket |
| TypeBox JSON Schema validation | Replaced by Pydantic models |
| jiti plugin loader (TypeScript modules at runtime) | Replaced by `nodus_extension` |
| Legacy Pi/Tau session folder compatibility | Not carried forward (new project) |
| `openclaw doctor` migrations | Replaced by config validation at startup |
| `vitest` test suite | Replaced by Nodus `std:test` + pytest |
| `pnpm` monorepo tooling | Replaced by Python package management |
