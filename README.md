# Infinity Claw

**The first agent built on the [Masterplan Infinite Weave](https://github.com/Masterplanner25) Framework.**

Infinity Claw is a production-grade personal AI assistant that serves as the reference implementation for building agents on the Nodus Language Ecosystem and the AINDY execution kernel. It is designed to be self-hosted, multi-channel, and zero-infrastructure by default — run it from a single config file with nothing but an Anthropic API key.

---

## What this demonstrates

| Layer | Technology |
|---|---|
| Agent orchestration DSL | [Nodus Language](https://github.com/Masterplanner25) (`nodus-lang` 4.0.5, 29-package runtime) |
| Execution kernel | AINDY runtime 1.4.0 — syscall dispatcher, MAS memory, Redis event bus, OTel |
| Gateway | FastAPI + WebSocket + REST control plane |
| Channels | WebChat (built-in), Discord, Telegram, Slack, Matrix, Signal |
| Memory | SQLite-backed semantic memory with per-agent recall injection |
| Sessions | Per-peer DM scoping, LLM-based compaction, message pruning |
| Scheduling | APScheduler cron jobs with configurable delivery |
| Auth | JWT issuance + persistent API key store |
| Skills | File-based skill system with allow/deny gating |
| Observability | OTel tracing via `nodus-observability-framework`; AINDY turn lifecycle events |

---

## Quick start

**Requirements:** Python 3.11+, an Anthropic API key.

```bash
git clone https://github.com/Masterplanner25/infinityclaw.git
cd infinityclaw

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -e .

cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY

claw start
# Gateway:  http://127.0.0.1:18789/
# WebChat:  http://127.0.0.1:18789/
# WebSocket ws://127.0.0.1:18789/ws/chat
# Health    http://127.0.0.1:18789/health
```

---

## Configuration

All configuration lives in `claw.toml`. The minimal setup:

```toml
[[agents.list]]
id = "main"
name = "Claw"
default = true
```

Environment variables override file values:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Primary LLM credential |
| `CLAW_GATEWAY_TOKEN` | Bearer token for gateway auth (omit to disable) |
| `AINDY_API_KEY` | AINDY platform key (enables kernel bridge) |
| `AINDY_URL` | AINDY runtime URL (default: `http://localhost:8000`) |

### AINDY integration

Set `[aindy] enabled = true` in `claw.toml` and provide `AINDY_API_KEY` to enable the AINDY bridge. When enabled, Infinity Claw emits turn lifecycle events (`sys.v1.claw.turn.start`, `sys.v1.claw.turn.complete`, `sys.v1.claw.turn.error`) as fire-and-forget syscalls. AINDY being unreachable never blocks a turn.

### Channel adapters

Uncomment and fill in the relevant section of `claw.toml`:

```toml
[channels.extra.telegram]
token = "BOT_TOKEN"

[channels.extra.discord]
token = "BOT_TOKEN"

[channels.extra.slack]
bot_token = "xoxb-..."
app_token  = "xapp-..."
```

---

## CLI

```bash
claw start              # start the gateway
claw start --daemon     # background process (POSIX)
claw stop               # send SIGTERM to daemon
claw status             # check if daemon is running
claw check              # validate config and exit
claw doctor             # health-check all subsystems
claw agents list        # list configured agents
claw cron list          # list cron jobs
```

---

## Nodus workflows

Startup and maintenance workflows live in `workflows/` as `.nd` (Nodus DSL) scripts:

```
workflows/
  boot.nd           # gateway boot sequence
  bootstrap.nd      # first-run workspace setup
  heartbeat.nd      # periodic health probe
  session_reset.nd  # scheduled session cleanup
```

---

## Project structure

```
claw/               # core package
  agents/           # agent registry, prompt builder, streaming turn
  aindy/            # async bridge to AINDY SDK
  auth/             # JWT + API key store
  channels/         # adapter registry, pairing, DM policy
  config/           # schema (Pydantic) + TOML/JSON loader
  cron/             # APScheduler cron manager
  gateway/          # FastAPI app, WebSocket handlers, auth middleware
  memory/           # MemoryManager, SQLite store, recall injection
  routing/          # binding resolver, inbound envelope
  sessions/         # session manager, compactor, pruner, key builder
  skills/           # loader, injector, allow/deny gate
  tools/            # tool registry, standard tools (browser_fetch, etc.)
  workspace/        # bootstrapper + initializer
claw_discord/       # Discord channel adapter
claw_matrix/        # Matrix channel adapter
claw_signal/        # Signal channel adapter
claw_slack/         # Slack channel adapter
claw_telegram/      # Telegram channel adapter
claw_webchat/       # Built-in browser chat UI + WebSocket adapter
workflows/          # Nodus DSL scripts
tests/              # milestone test suites (30/30 passing)
```

---

## Development

```bash
pip install pytest pytest-asyncio
pytest tests/ -q
```

The test suite runs against the real FastAPI ASGI app (no mocks). All 30 tests pass with `asyncio_mode = "auto"`.

---

## Masterplan Infinite Weave

Infinity Claw is the first concrete application in the **Masterplan Infinite Weave** — a framework for building interconnected agentic systems on the Nodus runtime. The Nodus Language Ecosystem provides the orchestration layer; AINDY provides the execution kernel, memory substrate, and event bus that agents share across the weave.

More agents, integrations, and documentation will follow.
