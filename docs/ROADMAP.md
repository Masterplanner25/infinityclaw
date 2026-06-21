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

### Phase 10 — Session-Persistent Delegation ✅
*Delegated agents accumulate conversation history within a caller session*

**Problem solved:** `delegate_to_agent` previously passed a fresh single-message history each call — the target agent started from scratch on every delegation, with no knowledge of prior exchanges.

**What was built:**
- `HandoffRequest.session_key` — new field threads the delegation session key through the dispatch chain
- `run_agent_turn(session_key="")` — when `session_key` is provided, uses `ClawSessionManager` (lock + append + compact + prune) so history persists across calls. When empty, stateless Phase 8 behavior.
- `scoped_executor` in `_run_turn` now injects `_session_key` (the caller's session key) alongside `_agent_id` for coordination tools
- `delegate_to_agent` handler derives a stable delegation key `delegate:{from}:{caller_session}:{to}` and passes it as `HandoffRequest.session_key` — the LLM needs no new parameters
- `AgentDispatcher.dispatch` passes `session_key` through to `run_agent_turn`
- `tests/test_aindy_phase10.py` — 26 checks, 13 pytest-collected functions

---

### Phase 11 — Delegation Audit Trail ✅
*Cross-agent handoffs visible in the AINDY audit log alongside turns and memory writes*

**Problem solved:** `delegate_to_agent` previously fired no AINDY events — cross-agent handoffs were invisible in the audit log.

**What was built:**
- `_emit_event(client, event_type, payload)` module-level helper in `dispatcher.py` — same fire-and-forget pattern as `_emit_aindy` in `server.py`; swallows all exceptions
- `delegation_id = str(uuid.uuid4())` generated per `dispatch()` call for log correlation
- `claw.delegation.started` — fired before `run_agent_turn` for known agents; payload: `{from_agent, to_agent, delegation_id, persistent, session_key?}`
- `claw.delegation.complete` — fired on success; adds `response_len`
- `claw.delegation.error` — fired when `run_agent_turn` returns an `[error:...]` string; adds `error` (truncated to 200 chars)
- Unknown-agent short-circuit returns error immediately with **no events** (no delegation was started)
- Gated behind `self._gw._aindy and self._gw.config.aindy.emit_events` — same as all other AINDY events
- `tests/test_aindy_phase11.py` — 33 checks, 11 pytest-collected functions

---

### Phase 12 — Distributed Workspaces (Weave) ✅
*Multiple Claw instances form a peer network; agents delegate across nodes*

**Capabilities unlocked:**
- An agent on Node A can delegate tasks to an agent running on Node B
- Cross-node delegation is session-persistent: `weave:{from_node}:{session}:{to_node}:{agent}` key accumulates history
- Peer node discovery: `weave_list_nodes` / `weave_list_agents` tools let agents find remote agents
- Node registration via REST (`POST /weave/nodes/register`) and CLI (`claw weave connect`)
- Weave-wide agent listing at `GET /weave/agents` (each node exposes its own agent roster)

**Work (complete):**
- `claw/weave/model.py` — `WeaveNode`, `WeaveDelegateRequest`, `WeaveRegisterRequest`, `get_or_create_node_id()`
- `claw/weave/registry.py` — `WeaveNodeStore`: SQLite peer registry (`INSERT OR REPLACE`; `":memory:"` for tests)
- `claw/weave/client.py` — `WeaveClient`: `httpx.AsyncClient`; `ping`, `list_agents`, `delegate`, `register_self`; all methods swallow exceptions and return safe defaults
- `claw/weave/tools.py` — `weave_delegate`, `weave_list_nodes`, `weave_list_agents`; `is_weave_tool()`; `register_weave_tools()`
- `claw/config/schema.py` — `WeaveConfig(enabled, node_id, db_path)` + `ClawConfig.weave` field
- `claw/gateway/server.py` — `weave_store`, `weave_client`, `_weave_node_id`, `weave_node_id` property; Weave init in `__init__`; `register_weave_tools()` in `startup()`; `is_weave_tool` injection in both `scoped_executor` and `_inner_exec`; `/weave/*` REST endpoints in `_build_claw_router` (conditional on `weave.enabled`)
- `claw/cli.py` — `claw weave status/nodes/connect/disconnect` subcommands
- `tests/test_aindy_phase12.py` — 38 checks, 28 pytest-collected functions

---

### Phase 13 — Cross-Node Workspace Federation ✅
*Agents read workspace documents and tasks from peer Weave nodes on demand*

**Capabilities unlocked:**
- An agent on Node B can list and read documents from Node A's workspace
- An agent on Node B can list tasks from Node A's workspace (with optional status filter)
- Pull-on-read: data is fetched live; no background sync needed
- Peer-trust model: any registered peer node may read — admin controls access via the peer registry

**Work (complete):**
- `WeaveClient`: `fetch_documents(node, agent_id)`, `fetch_document(node, agent_id, doc_id) -> dict|None`, `fetch_tasks(node, agent_id, status="")`
- Tools: `weave_list_workspace_documents`, `weave_read_document`, `weave_list_workspace_tasks` — registered via `register_weave_tools()`, injection via `is_weave_tool`
- REST endpoints (gated on both `weave.enabled` and `workspace.enabled`): `GET /weave/workspace/{agent_id}/documents`, `GET /weave/workspace/{agent_id}/documents/{doc_id}`, `GET /weave/workspace/{agent_id}/tasks?status=...`
- Document endpoint verifies `doc.workspace_id == agent_id` to prevent cross-workspace leakage
- `tests/test_aindy_phase13.py` — 28 checks, 16 pytest-collected functions

---

### Phase 14 — Weave-Wide Agent Discovery & Cross-Node Writes ✅
*Agents discover peers across the whole Weave and write to remote workspaces*

**Capabilities unlocked:**
- `weave_discover_agents` — queries all registered peers concurrently; unified agent roster with node attribution; unreachable nodes silently skipped
- Remote document and task creation/update via cross-node write tools
- Knowledge index federation: search a remote node's FTS5 knowledge index

**Work (complete):**
- `claw/weave/model.py` — `WeaveCreateDocumentRequest`, `WeaveCreateTaskRequest`, `WeaveUpdateTaskRequest` request models
- `WeaveClient` — `list_all_agents(nodes)` (`asyncio.gather` + skip-failed-nodes via `isinstance(agents, list)` check; adds `node_id` + `node_url` attribution); `create_document`, `create_task`, `update_task` (returns `None` on 404), `search_knowledge`
- `claw/weave/tools.py` — 5 new tools: `weave_discover_agents`, `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge`; `_WEAVE_TOOLS` frozenset now 11 entries
- REST write endpoints (gated on `workspace.enabled`): `POST /weave/workspace/{agent_id}/documents`, `POST /weave/workspace/{agent_id}/tasks`, `PATCH /weave/workspace/{agent_id}/tasks/{task_id}`
- REST knowledge endpoint (gated on `knowledge.enabled`): `GET /weave/workspace/{agent_id}/knowledge?q=...&limit=...` — calls `knowledge_index.search()` directly via `asyncio.to_thread`; serializes `Chunk` dataclass via `dataclasses.asdict()`
- `tests/test_aindy_phase14.py` — 32 checks, 18 pytest-collected functions

---

## Planned

## Future Considerations (unscheduled)

- **Voice interface** — speech-to-text input, text-to-speech response delivery
- **Mobile companion** — Infinity Claw control from iOS/Android (pairs via QR code + pairing protocol)
- **Eval framework** — automated quality measurement across agent responses and memory recall
- **Plugin ecosystem** — third-party channel adapters, knowledge ingestion parsers, tool packs
- **Workspace templates** — bootstrap a workspace with predefined documents, memories, and agent configs for common use cases (developer workspace, research workspace, writing workspace)
