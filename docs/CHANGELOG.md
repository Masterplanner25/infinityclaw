# Changelog — Infinity Claw

All notable changes are documented here. Infinity Claw follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — 2026-06-20

Initial release. Fourteen integration phases shipped as a single version.

### Foundation (Phases 1–4)

- FastAPI gateway with WebSocket and REST control plane
- Multi-agent registry with per-agent credential stores and isolated sessions
- Memory subsystem — SQLite-backed, per-agent namespaced, semantic recall
- Session management — DM scoping, LLM compaction, message pruning, daily reset
- Channel adapters: WebChat, Discord, Telegram, Slack, Matrix, Signal
- Skill system — file-based, global and per-agent allow/deny gating
- Auth — JWT issuance, persistent API key store, static bearer token
- Cron jobs — APScheduler, configurable delivery modes (announce / webhook / none)
- CLI — `start`, `stop`, `status`, `check`, `doctor`, `agents`, `workspace`, `weave`, `cron`
- AINDY bridge — turn lifecycle events (`turn.start`, `turn.complete`, `turn.error`, `session.started`, `session.ended`, `memory.written`, `cron.executed`) via fire-and-forget `asyncio.create_task`
- AINDY memory backend — `local`, `aindy`, `aindy-fallback` modes
- Execution tracking — `execution_unit_id` per turn propagated to memory writes and AINDY events
- Gateway mount — `_build_claw_router()` for AINDY platform layer registration; `aindy.mounted` mode bypasses auth and suppresses health routes

### Knowledge layer (Phase 5 + follow-on)

- `claw/knowledge/` — document ingestion, SQLite FTS5 index, BM25 ranked retrieval
- Supported formats: Markdown, plaintext, HTML, Python, JavaScript/TypeScript, Go, Rust, CSV
- `KnowledgeRetriever` — async top-K chunk retrieval injected into system prompt
- `KnowledgeWatcher` — `watchfiles`-based background auto-reindex on workspace file changes
- `claw workspace index [--agent ID]` — on-demand reindex CLI command

### Workspace objects (Phase 6)

- `claw/workspace/` — Documents, Tasks, Assets, Permissions with SQLite backing
- Six agent tools: `ws_create_document`, `ws_list_documents`, `ws_get_document`, `ws_create_task`, `ws_list_tasks`, `ws_update_task`
- Per-agent permissions: `none`, `read`, `write`; owner always has full access
- `claw workspace create / list / share` CLI commands

### Permissions (Phase 7)

- `claw/permissions/` — `CapabilitySet` per agent: `tool_use`, `skill_use`, `external_http`, `filesystem`
- `PermissionEnforcer` — `filter_tool_definitions()` strips denied tools before LLM sees them; `check_tool_call()` enforces at invocation
- Private network block for `browser_fetch` — RFC-1918 + loopback, always on, no config switch

### Multi-agent coordination (Phases 8–11)

- `claw/coordination/` — `AgentDispatcher`, `delegate_to_agent` tool, `run_agent_turn()`
- Per-agent skill gating via `capabilities.skill_use`
- Cross-agent memory recall via `cross_agent_memory` on `[[agents.list]]`
- Cross-workspace tool access via `target_agent_id` parameter (Phase 9)
- Session-persistent delegation — `delegate:{from}:{session}:{to}` key accumulates history (Phase 10)
- Delegation audit trail — `claw.delegation.started/complete/error` AINDY events with `delegation_id` correlation (Phase 11)

### Distributed Weave (Phases 12–14)

- `claw/weave/` — SQLite peer registry (`WeaveNodeStore`), httpx cross-node HTTP client (`WeaveClient`)
- Auto-generated persistent `node_id` UUID stored at `<state_dir>/node_id`
- 11 agent tools: `weave_delegate`, `weave_list_nodes`, `weave_list_agents`, `weave_list_workspace_documents`, `weave_read_document`, `weave_list_workspace_tasks`, `weave_discover_agents`, `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge`
- REST endpoints: peer registration, cross-node delegation, workspace federation (read + write), knowledge search
- Cross-node workspace federation — pull-on-read, peer-trust model (Phase 13)
- Weave-wide agent discovery — concurrent `asyncio.gather` across all registered nodes; skip-failed-nodes (Phase 14)
- Cross-node workspace writes — create/update documents and tasks on remote nodes (Phase 14)
- Cross-node knowledge search — FTS5 search across remote knowledge indexes (Phase 14)
- `claw weave status/nodes/connect/disconnect` CLI commands

### Dependencies

- Python 3.11+
- nodus-lang 4.0.6, 29-package Nodus ecosystem
- aindy-runtime 1.4.0
- FastAPI + Uvicorn
- Anthropic SDK (async streaming)
- httpx (browser tool, Weave HTTP client)
- APScheduler (cron)
- watchfiles (knowledge watcher)

---

## Versioning policy

Infinity Claw is currently at v0.1.x (pre-stable). Breaking changes may occur between minor versions. Once the public API stabilises, the project will move to v1.0.0 and follow strict semantic versioning.

Future planned work:

- v0.2.x — workspace data replication, Weave-wide knowledge federation
- v0.3.x — voice interface, mobile companion pairing
- v1.0.0 — stable API, eval framework, plugin ecosystem
