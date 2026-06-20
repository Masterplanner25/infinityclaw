# Roadmap — Infinity Claw

This roadmap tracks capabilities, not features. Each phase adds a new category of what Infinity Claw can do — not just what it ships with.

---

## Completed

### Phase 1 — Foundation
*Gateway + agent runtime + channels*

- FastAPI gateway with WebSocket + REST control plane
- Multi-agent registry (per-agent credential store, isolated sessions)
- Memory (SQLite-backed, per-agent namespaced, semantic recall)
- Session management (DM scoping, LLM compaction, message pruning)
- Channel adapters: WebChat, Discord, Telegram, Slack, Matrix, Signal
- Skill system (file-based, allow/deny gated)
- Auth (JWT issuance, persistent API key store, static bearer token)
- Cron jobs (APScheduler, configurable delivery modes)
- CLI (start, stop, status, check, doctor, agents, cron)
- AINDY bridge — turn lifecycle events (fire-and-forget)

### Phase 2 — AINDY Memory Backend
*Agent memory routes through AINDY MAS*

- `AINDYMemoryStore` — async, namespaced, MAS path convention
- `MemoryManager` async methods route through AINDY or fall back to local SQLite
- Three memory backends: `local`, `aindy`, `aindy-fallback`
- `remember()` accepts `execution_unit_id`, threading it into `MemoryNode.extra`

### Phase 3 — Execution Tracking
*Every turn and cron job has an audit trail*

- `execution_unit_id` (UUID) generated per turn; propagated to memory writes and AINDY events
- `claw.session.started` / `claw.session.ended` events on WebSocket lifecycle
- `claw.memory.written` event on every AINDY MAS write
- `sys.v1.job.submit` + `claw.cron.executed` on cron job execution
- `CronManager` AINDY event helpers (`_fire_aindy_event`, `_fire_aindy_job`)

### Phase 4 — Gateway Mount
*Claw runs standalone or inside the AINDY platform layer*

- `_build_claw_router()` extracts all Claw routes into an `APIRouter`
- `build_app()` dual-mode: standalone (with health/observability) vs. mounted (Claw routes only)
- `GatewayAuth(bypass=True)` for mounted mode — AINDY platform layer handles auth
- `claw/aindy/app_registration.py` — `register_claw_app()` async entry point for AINDY platform

### Phase 5 — Knowledge Layer
*Workspace files become indexed, retrievable knowledge*

**Capabilities unlocked:**
- Ingest documents (Markdown, plaintext, HTML, code, CSV) into a keyword index
- Retrieve relevant chunks at turn time; only relevant content injected into context
- Support workspaces with many documents without context window pressure
- On-demand reindex: `claw workspace index [--agent ID]`

**Work (complete):**
- `claw/knowledge/ingestion.py` — `Chunk` dataclass, `parse_file()`, `chunk_text()`, `ingest_file()`
- `claw/knowledge/index.py` — `KnowledgeIndex`: two-table SQLite FTS5 schema, BM25 ranked search
- `claw/knowledge/retrieval.py` — `KnowledgeRetriever`: async wrapper (`asyncio.to_thread`)
- `claw/knowledge/injector.py` — `KnowledgeInjector`: formats `## Relevant Knowledge` prompt section
- `claw/knowledge/scanner.py` — `WorkspaceScanner`: finds indexable files, excludes identity/boot files
- `PromptContext.knowledge_block` field; injected after memories, before skills
- `KnowledgeConfig` in `ClawConfig`; startup scan on `ClawGateway.startup()`
- `claw workspace index` CLI command
- `tests/test_aindy_phase5.py` — 38 checks, 12 pytest-collected tests

### Phase 6 — Workspace as First-Class Object
*Workspaces become explicit, shareable, multi-agent containers*

**Capabilities unlocked:**
- Multiple agents operating inside one workspace with role-based access
- Workspace objects: Documents, Tasks, Assets with stable IDs
- Per-agent permissions (read/write/none) enforced at manager level
- Agents can create and manage documents and tasks across sessions via tools

**Work (complete):**
- `claw/workspace/model.py` — `Workspace`, `Document`, `Task`, `Asset`, `WorkspacePermission` data models
- `claw/workspace/store.py` — `WorkspaceStore`: SQLite-backed, five-table schema
- `claw/workspace/manager.py` — `WorkspaceManager`: async interface, `ensure_workspace()`, `can_read()`, `can_write()`
- `claw/workspace/tools.py` — 6 agent tools: `ws_create_task`, `ws_list_tasks`, `ws_update_task`, `ws_create_document`, `ws_list_documents`, `ws_get_document`
- `WorkspaceConfig` in `claw/config/schema.py`; `ClawGateway` wires manager + tools in startup
- `claw workspace create / list / share` CLI commands
- `tests/test_aindy_phase6.py` — 73 checks, 12 pytest-collected tests

### Phase 6 — Follow-Ons
*Knowledge layer upgrades*

**Work (complete):**
- `claw/knowledge/watcher.py` — `KnowledgeWatcher`: background `watchfiles`-based watcher; auto-reindexes workspace files on create/modify/delete without requiring `claw workspace index`
- `ClawGateway.startup()` launches watcher task (cancellable via `_listener_tasks["knowledge-watcher"]`); watcher gracefully exits if `watchfiles` is not installed

### Phase 7 — Permissions and Filesystem Access
*Tool calls are gated by explicit per-agent capability declarations*

**Capabilities unlocked:**
- Tool allowlist/denylist per agent enforced at runtime before the LLM call and at invocation time
- Private network block for `browser_fetch` — always on; no config required
- HTTP allowlist and denylist per agent for `browser_fetch`
- Filesystem capability model declared in `claw.toml` per agent
- Framework ready for absolute-path filesystem tools (Phase 9+)

**Work (complete):**
- `claw/permissions/model.py` — `CapabilitySet`, `FilesystemPermission`, `HttpPermission`, `ToolPermission`, `SkillPermission`
- `claw/permissions/enforcer.py` — `PermissionDenied`, `PermissionEnforcer`: `filter_tool_definitions()` (strips denied tools from LLM tool list), `check_tool_call()` (enforces at invocation), `_is_private_host()` (RFC-1918 + loopback detection)
- `claw/config/schema.py` — `AgentConfig.capabilities: Optional[CapabilitySet]`; import from `claw.permissions.model`
- `claw/gateway/server.py` — `_run_turn` builds `PermissionEnforcer` from agent capabilities each turn; filters `tool_registry.definitions()` before passing to LLM; `scoped_executor` calls `check_tool_call` and returns `{"error": "permission denied: ..."}` on violation
- `tests/test_aindy_phase7.py` — 37 checks, 16 pytest-collected tests

### Phase 8 — Multi-Agent Coordination
*Agents delegate tasks to each other*

**Capabilities unlocked:**
- One agent can hand off a task to a specialized agent and receive its response
- Coordinator pattern: planner agent sends prompts to executor agents via `delegate_to_agent` tool
- Per-agent skill gating: `capabilities.skill_use.allow/deny` restricts which skills each agent can use
- Cross-agent memory: an agent can optionally read another agent's memories (opt-in, declared in config)

**Work (complete):**
- `claw/coordination/model.py` — `HandoffRequest`, `HandoffResult` data models
- `claw/coordination/dispatcher.py` — `AgentDispatcher.dispatch()`: stateless inner-turn dispatch
- `claw/coordination/tools.py` — `delegate_to_agent` tool + `is_coordination_tool()` predicate
- `ClawGateway.run_agent_turn()` — headless inner turn (no session, no channel delivery)
- `claw/config/schema.py` — `CoordinationConfig(enabled=False)` on `ClawConfig`; `cross_agent_memory: list[str]` on `AgentConfig`
- `claw/skills/gating.py` — `SkillGate.filter()` now treats `["*"]` in allow as wildcard (allow all)
- `claw/gateway/server.py` — per-agent skill gate in `_run_turn`; cross-agent memory recall; delegation tool registration in `startup()`; `_agent_id` injection for coordination tools in `scoped_executor`
- `tests/test_aindy_phase8.py` — 29 checks, 14 pytest-collected tests

---

### Phase 9 — Cross-Workspace Tool Access
*Agents operate on each other's workspaces with permission*

**Capabilities unlocked:**
- One agent can read or write another agent's workspace documents and tasks
- Permission model enforced at the tool level: read vs. write grants distinct access levels
- ID-based tools (`ws_get_document`, `ws_update_task`) automatically enforce permissions via the object's workspace ownership
- `target_agent_id` parameter on list/create tools selects the target workspace

**Work (complete):**
- `claw/workspace/tools.py` — all 6 `ws_*` tools updated with cross-workspace support:
  - `ws_create_task`, `ws_list_tasks`, `ws_create_document`, `ws_list_documents`: optional `target_agent_id` param; `can_write`/`can_read` checked when target differs from caller
  - `ws_update_task`, `ws_get_document`: look up object first, enforce `can_write`/`can_read` if `workspace_id != calling_agent`
- All results include `workspace_id` field
- `tests/test_aindy_phase9.py` — 30 checks, 18 pytest-collected tests

---

## Planned

### Phase 10 — Distributed Workspaces
*Workspaces span multiple Claw instances across the Weave*

**Capabilities unlocked:**
- A workspace hosted on one Claw instance is accessible to agents on another
- Knowledge, memories, and tasks replicate across Weave nodes
- An agent on Node A can query the workspace of Node B (with permission)
- Weave-wide agent discovery: "find me an agent that can do X"

**Work:**
- AINDY Weave topology integration (node registry, routing)
- Workspace replication protocol (AINDY event bus + MAS sync)
- Cross-node session handoff
- Weave-scoped agent registry
- `claw weave` CLI commands

---

## Future Considerations (unscheduled)

- **Voice interface** — speech-to-text input, text-to-speech response delivery
- **Mobile companion** — Infinity Claw control from iOS/Android (pairs via QR code + pairing protocol)
- **Eval framework** — automated quality measurement across agent responses and memory recall
- **Plugin ecosystem** — third-party channel adapters, knowledge ingestion parsers, tool packs
- **Workspace templates** — bootstrap a workspace with predefined documents, memories, and agent configs for common use cases (developer workspace, research workspace, writing workspace)
