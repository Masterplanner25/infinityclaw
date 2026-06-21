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

### Phase 15 — Operational Hardening ✅
*Stable for personal use*

Phase 15 closes the gap between "feature complete" and "reliably runnable." No new capabilities — only the operational foundations that make the system trustworthy to depend on day-to-day.

**What was built:**

- `claw backup [--output <path>]` — archives all enabled SQLite stores (memory, workspace, weave) to a timestamped `.tar.gz` with a `manifest.json` (claw version, timestamp, per-store schema version)
- `claw restore <archive>` — validates manifest, checks schema version parity before overwriting, restores each store to its configured path; exits with error on version mismatch
- Schema versioning — `SCHEMA_VERSION = 1` constant + `schema_version` table in `MemorySqliteStore`, `WorkspaceStore`, and `WeaveNodeStore`; version is stamped on first init; future upgrades add migration branches, no manual DB surgery required
- Expanded `claw doctor`:
  - `_db_integrity_ok(path)` helper — `PRAGMA integrity_check` per enabled store; reports `[FAIL]` on corruption or missing file
  - Weave peer reachability — pings each registered peer node, reports `[OK]`/`[WARN]` per node with truncated node ID
  - `_check_config_consistency(cfg)` helper — warns on `memory_backend="aindy"` without `aindy.enabled = true`; warns on inline secrets in `gateway.token`, `aindy.api_key`, and credential `api_key` fields (env var refs like `$VAR` are not flagged)
- `tests/test_aindy_phase15.py` — 22 assertions across 22 pytest-collected functions (240/240 total)

---

## Public Product Path

> **Context:** Claw's primary purpose is to demonstrate the Masterplan Infinite Weave Framework and AINDY architecture. The phases below are what "public release" would require if the project ever moves beyond personal use and demonstration. They are not currently active.

> **License decision (resolved):** Apache 2.0. MIT-compatible (AINDY is MIT), permissive, enterprise-friendly, patent grants included. A `LICENSE` file is added in Phase 17 alongside the distribution work. No CLA required — this is not a commercial open-core project.

### Phase 16 — Security Hardening
*Safe to expose to other people*

**Goal:** Closes the gap between "works for me" and "safe to run as a service others connect to." No new features — adversarial review of the existing surface.

**Work:**
- Rate limiting via `slowapi` — per-session and per-API-key limits on turn and REST endpoints; configurable in `claw.toml`
- Secret detection in `claw doctor` — warn when JWT secrets, API keys, or bearer tokens appear hardcoded in `claw.toml` (regex on known field names and common secret patterns)
- SSRF audit — systematic review of all external HTTP paths beyond `browser_fetch`; document the full threat model and any mitigations added
- Input validation review — adversarial pass over tool input schemas and REST request models; harden anything that processes user-supplied strings as paths, URLs, or IDs
- `SECURITY.md` — responsible disclosure policy and contact

### Phase 17 — Distribution & Onboarding
*Installable by someone who isn't the author*

**Goal:** A developer who has never seen the repo can go from zero to a running Claw instance in under 15 minutes.

**Work:**
- `LICENSE` — Apache 2.0
- PyPI package — `pip install infinity-claw`; entry point `claw` registered via `pyproject.toml`
- Docker image + `docker-compose.yml` — covers the common standalone configuration (single node, WebChat, SQLite stores mounted as volumes)
- `claw init` wizard — interactive first-run that generates a starter `claw.toml` with sane defaults; prompts for agent name, API key, and channel selection; validates the result before writing
- API version prefix — all REST endpoints move to `/v1/...`; old paths removed (not shimmed); stability guarantee documented in `API_REFERENCE.md`
- `CONTRIBUTING.md` — development setup, test conventions, PR process

### Phase 18 — Self-Hosted Observability
*Fully observable with standard OSS tooling; no AINDY required*

**Goal:** A self-hoster can wire Claw into their existing monitoring stack (Prometheus, Grafana, Loki, etc.) without running AINDY.

**Work:**
- Prometheus `/metrics` endpoint — turn counts, latency histograms, memory operation counts, active session gauge, Weave peer health; independent of AINDY; enabled by default in standalone mode
- Structured JSON logging — machine-parseable output for log aggregators (Loki, Datadog, CloudWatch); configurable format (`text` vs `json`) in `claw.toml`
- Log rotation config — `[logging] max_bytes` and `backup_count` in `claw.toml`; defaults that won't fill a disk on a long-running instance
- Basic health dashboard in WebChat UI — active agents, session counts, last turn timestamps, Weave peer status; visible to authenticated admin users

### Phase 19 — Ecosystem Surface
*Makes Claw a platform others can extend*

**Goal:** Third parties can build channel adapters, tool packs, and workspace templates without forking the core.

**Work:**
- Plugin/extension contract — documented interface for third-party channel adapters and tool packs; version-pinned API so plugins don't break on upgrades
- Workspace templates — `claw workspace init --template <name>` bootstraps a workspace with predefined documents, tasks, and agent configs; built-in templates for common use cases (developer, research, writing)
- `claw eval` — run a test prompt set against an agent and compare outputs; basic quality measurement for validating agent config changes
- Python SDK — typed REST + WebSocket client library for driving Claw from external code; published to PyPI alongside the main package

### Phase 20 — Managed Cloud *(if ever)*
*Run Claw as a multi-tenant hosted service*

**Decision criteria:** Only pursue if there is demonstrated external demand and a clear operator willing to run the infrastructure. This is a separate business decision, not a development milestone. The Weave architecture gives a head start on multi-node thinking, but multi-tenancy within a single node (per-user data isolation) is a distinct problem.

**Major additions required:**
- Per-user data isolation — memory, workspace, and weave stores scoped per user account, not per install; current agent-level namespacing is insufficient
- User accounts — registration, login, OAuth integration
- Billing integration
- GDPR/compliance surface — data export and deletion on request
- SLA operations — monitoring, alerting, on-call, incident response

---

## Deferred Weave Capabilities

These extend the Weave layer but are not required for stable personal use or public release. They are documented here because the architecture already anticipates them and the decision to build them is straightforward when the need arises.

### Option B — Workspace Replication ✓ COMPLETE
*Push-based sync of workspace objects across Weave peers*

**Implemented:** `[weave] sync = true` config flag (disabled by default). `WeaveClient.push_workspace()` fans out after local writes. `POST /weave/workspace/{agent_id}/sync` receives batches from peers. `WorkspaceStore.sync_document()` and `upsert_task()` apply last-write-wins by `updated_at`. Sync hook wired into `ws_create_document`, `ws_create_task`, `ws_update_task` tools via fire-and-forget `asyncio.create_task`. Incoming sync paths do not trigger re-sync (loop-safe). 23 tests in `tests/test_weave_sync.py`.

### Option C — Knowledge Federation ✓ COMPLETE
*Pull-and-cache a peer node's knowledge index locally*

**Implemented:** `GET /weave/workspace/{agent_id}/knowledge/export` endpoint (gated on `weave.enabled AND knowledge.enabled`) returns all `Chunk` dicts via `KnowledgeIndex.export_chunks()`. `WeaveClient.pull_knowledge_index(node, agent_id, local_index)` fetches and replaces `peer:{node_id}:{agent_id}` namespace (clear + upsert_many via asyncio.to_thread; skips empty-content chunks; returns count). `claw weave sync-knowledge <node_id> <agent_id>` CLI for one-shot pulls. Background `_knowledge_sync_loop` task started in `ClawGateway.startup()` when `weave.knowledge_sync_interval > 0`; first sync fires after one interval (not on startup); stored in `_listener_tasks["weave-knowledge-sync"]` for clean shutdown. 22 tests in `tests/test_weave_knowledge_sync.py`.

---

## Future Considerations (unscheduled)

- **Voice interface** — speech-to-text input, text-to-speech response delivery
- **Mobile companion** — Infinity Claw control from iOS/Android (pairs via QR code + pairing protocol)
- **Eval framework** — automated quality measurement across agent responses and memory recall (stub exists in Phase 19; full implementation is a later concern)
- **Plugin ecosystem** — third-party channel adapters, knowledge ingestion parsers, tool packs (contract defined in Phase 19; ecosystem growth is unscheduled)
- **Workspace templates** — bootstrap a workspace with predefined documents, memories, and agent configs for common use cases (Phase 19 includes the mechanism; additional templates are unscheduled)
