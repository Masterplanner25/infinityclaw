# Infinity Claw — Claude Code context

## Project identity

**Infinity Claw** (`claw` package, `C:\dev\claw`) is the first agent built on the Masterplan Infinite Weave Framework. It showcases the Nodus Language Ecosystem (nodus-lang 4.0.6, 29-package runtime) integrated with the AINDY execution kernel (aindy-runtime 1.4.0) as a production-grade personal AI assistant.

- GitHub: https://github.com/Masterplanner25/infinityclaw
- Package version: 0.1.0
- Python: 3.11+ (venv at `C:\dev\claw\venv`)
- Tests: `pytest tests/ -q` → 218/218 (never break this baseline)

## How to run

Full `claw.toml` configuration reference: `docs/CONFIGURATION.md`. Channel adapter setup: `docs/CHANNELS.md`. Deployment guide: `docs/DEPLOYMENT.md`.

```powershell
venv\Scripts\python.exe -m claw start          # gateway at http://127.0.0.1:18789/
venv\Scripts\python.exe -m pytest tests/ -q    # test suite
venv\Scripts\python.exe -m claw doctor         # subsystem health check
venv\Scripts\python.exe -m claw workspace index  # re-index workspace files (requires knowledge.enabled = true)
venv\Scripts\python.exe -m claw workspace create <name> --agent <id>  # create a workspace object for an agent (requires workspace.enabled = true)
venv\Scripts\python.exe -m claw workspace list   # list workspaces (requires workspace.enabled = true)
venv\Scripts\python.exe -m claw workspace share <id> --agent <id> --perm <read|write|none>
venv\Scripts\python.exe -m claw weave status            # show local node_id + peer count (requires weave.enabled = true)
venv\Scripts\python.exe -m claw weave nodes             # list registered peer nodes
venv\Scripts\python.exe -m claw weave connect <url>     # register a remote Weave node
venv\Scripts\python.exe -m claw weave disconnect <id>   # remove a registered peer
```

## Architecture overview

```
claw/gateway/server.py   ClawGateway + build_app()
  ├── AgentRegistry      credential store, ConversationalTurn per agent
  ├── ClawSessionManager asyncio.Lock per session key; compaction + pruning
  ├── ChannelAdapterRegistry  WebChat + external adapters
  ├── BindingResolver    channel/peer → agent_id routing
  ├── SkillLoader/Gate   file-based skills with global allow/deny
  ├── MemoryManager      SQLite recall + injection
  ├── ToolRegistry       shared tool defs; scoped_executor enforces permissions + injects agent_id
  ├── CronManager        APScheduler cron jobs
  ├── AuthManager        JWT issuance + SqliteApiKeyStore
  ├── KnowledgeIndex     SQLite FTS5 workspace knowledge index (optional)
  ├── KnowledgeRetriever async retrieval wrapper; top-K chunks per turn
  ├── KnowledgeInjector  formats chunks into ## Relevant Knowledge prompt block
  ├── KnowledgeWatcher   watchfiles-based background task; auto-reindexes on change (optional)
  ├── WorkspaceStore     SQLite workspace object store (optional)
  ├── WorkspaceManager   async wrapper; Documents, Tasks, Assets, Permissions per agent
  ├── AgentDispatcher    session-persistent or stateless inner-turn dispatch for agent delegation (optional)
  ├── WeaveNodeStore     SQLite peer-node registry (optional; claw/weave/registry.py)
  ├── WeaveClient        httpx-based cross-node HTTP client (optional; claw/weave/client.py)
  └── _AsyncAINDYClient  optional AINDY bridge (claw/aindy/client.py)
  [per-turn, not stored on gateway]
  └── PermissionEnforcer built fresh each _run_turn from agent_cfg.capabilities
```

`build_app(cfg)` returns `(FastAPI, ClawGateway)` — this signature is test-critical, do not change it.

The FastAPI app uses a `lifespan` context manager (not `@app.on_event`, which is deprecated and was removed in the Phase 1 AINDY work).

## Key subsystems

### Turn pipeline (`_run_turn` in server.py)
1. Detect `is_new_session` (empty history check — must happen **before** appending the user message)
2. Generate `execution_unit_id = str(uuid.uuid4())` — threads through memory writes, AINDY events, tool calls
3. Load workspace files + skills; apply global `SkillGate`, then per-agent `SkillGate` from `capabilities.skill_use`
4. Recall memories (own agent); also recall from `cross_agent_memory` agents (up to 3 each) if configured
5. Retrieve knowledge chunks (if enabled); build system prompt via `PromptContext`
6. Append user message; compact if needed; prune
7. Fire AINDY events: `claw.session.started` if new session, `sys.v1.claw.turn.start` (both fire-and-forget, skipped if AINDY disabled)
8. Build `PermissionEnforcer(agent_cfg.capabilities)`; call `filter_tool_definitions()` to remove denied tools from the list passed to the LLM
9. `await turn.run(...)` via `scoped_executor` which: (a) calls `enforcer.check_tool_call()` — returns JSON error on `PermissionDenied`; (b) injects `agent_id` + `execution_unit_id` for memory/workspace/coordination/weave tools; streams chunks to WebChat or collects for other channels
10. Append assistant message; deliver response
11. Fire AINDY `turn.complete` or `turn.error` event

### Session management
- `asyncio.Lock` per session key — **not** `nodus_queue`. Sessions are serialized per-key, concurrent across different keys.
- `ClawSessionManager.compact_if_needed()` calls the LLM to summarize when `len(messages) >= compaction_threshold` (default 40), keeping the last `compaction_keep_recent` (default 20) messages.

### Memory tools
- Tools registered once on the shared `ToolRegistry`; `agent_id` **and** `execution_unit_id` are injected per-turn by `scoped_executor`. The LLM never sees or passes either value.
- `MemoryConfig.db_path = ":memory:"` → `InMemoryStore` (used by tests). Empty string → `~/.claw/memory.db`. Always use `":memory:"` in tests.
- `MemorySqliteStore` uses `sqlite3` (sync), not `aiosqlite` — the `MemoryStore` protocol is entirely synchronous.
- **`MemoryManager` public methods are async**: `remember()`, `recall()`, `list_all()`, `get()`, `forget()` all `await`. Only `feedback()` remains sync. In async tests use `await`; in sync tests use `asyncio.run()`.
- `AINDYMemoryStore` is **not** a `MemoryStore` implementor. It is async-native and called directly by `MemoryManager`. The `MemoryStore` protocol is for local SQLite only.
- Memory backend is set via `[aindy] memory_backend`: `"local"` (SQLite only), `"aindy"` (AINDY MAS, raises on failure), `"aindy-fallback"` (AINDY with automatic SQLite fallback).

### Knowledge layer (`claw/knowledge/`)
See `docs/tutorials/02-knowledge-layer.md` for a setup walkthrough. `docs/KNOWLEDGE_MODEL.md` covers the design.
- **Enabled** via `[knowledge] enabled = true` in `claw.toml`. Disabled by default.
- `WorkspaceScanner` finds files in the agent workspace directory that are NOT in `ALL_WORKSPACE_FILES` (identity/boot files) and have a supported extension.
- `ingest_file(path, workspace_id, chunk_size, chunk_overlap)` parses + chunks a file into `Chunk` objects (UUID chunk_id generated fresh each call).
- `KnowledgeIndex` — two-table SQLite schema: `knowledge_chunks` (metadata + `fts_rowid` FK) + `knowledge_fts` (FTS5 virtual table). `clear_source()` deletes FTS5 entries by rowid before deleting from base table.
- `KnowledgeRetriever.retrieve()` is async (wraps `index.search()` via `asyncio.to_thread`). FTS5 query uses OR of extracted words; rank is BM25 (lower/more negative = better match).
- `KnowledgeInjector.build_block()` formats a `## Relevant Knowledge` section for the system prompt.
- Startup scan: on `ClawGateway.startup()`, all workspace files (per agent) are scanned and indexed.
- `claw workspace index [--agent ID]` CLI command re-indexes on demand.
- `PromptContext.knowledge_block` injected between memories and skills in `SystemPromptBuilder`.

### Workspace object layer (`claw/workspace/`)
- **Enabled** via `[workspace] enabled = true` in `claw.toml`. Disabled by default.
- `WorkspaceStore` — SQLite store (sync, like `MemorySqliteStore`) with five tables: `workspaces`, `ws_documents`, `ws_tasks`, `ws_assets`, `ws_permissions`. Pass `db_path=":memory:"` in tests.
- `WorkspaceManager` — async wrapper via `asyncio.to_thread`. Each agent gets a home workspace with `id == agent_id`, created via `ensure_workspace()` (idempotent).
- Objects: `Workspace`, `Document`, `Task` (status: open/in_progress/done/cancelled), `Asset`, `WorkspacePermission` (level: none/read/write).
- **Permissions**: owner always has full read/write; other agents need an explicit grant via `set_permission()`. `can_read()` and `can_write()` are async.
- **Tools** (`claw/workspace/tools.py`): `ws_create_task`, `ws_list_tasks`, `ws_update_task`, `ws_create_document`, `ws_list_documents`, `ws_get_document`. Registered via `register_workspace_tools()` in `startup()`. Agent_id injected by `scoped_executor` (LLM never sees it). Pass `target_agent_id` on list/create tools for cross-workspace access (requires explicit permission); ID-based tools (`ws_get_document`, `ws_update_task`) enforce permissions automatically via the object's `workspace_id`.
- Startup: `ensure_workspace(agent_id)` called for each agent so the home workspace exists before tools run.
- `WorkspaceConfig.db_path = ":memory:"` for tests.
- CLI: `claw workspace create <name>`, `claw workspace list`, `claw workspace share <id> --agent <id> --perm <level>`

### Permissions layer (`claw/permissions/`)
- **Always active** — `PermissionEnforcer` is created per turn in `_run_turn`; no config flag needed.
- `CapabilitySet` (in `model.py`): `filesystem`, `external_http`, `tool_use`, `skill_use` — all fields default to open/unrestricted.
- Declared per-agent in `claw.toml` as `capabilities = { tool_use = { deny = ["write_file"] }, ... }` on `[[agents.list]]`.
- `AgentConfig.capabilities: Optional[CapabilitySet]` — `None` means full access (no restrictions).
- `filter_tool_definitions(defs)` — strips denied/non-allowed tools from the LLM's tool list before the turn starts.
- `check_tool_call(name, inp)` — called inside `scoped_executor` before every handler; raises `PermissionDenied` on violation; gateway returns `{"error": "permission denied: ..."}` to the LLM.
- **Private network block** for `browser_fetch` is always on regardless of config: `localhost`, `127.x`, `10.x`, `192.168.x`, `172.16-31.x`, `::1`.
- `external_http.allowlist`: empty = any public URL; non-empty = URL must start with one of the entries.
- `external_http.denylist`: URL must not contain any entry.
- `filesystem.paths`: when set, resolved path must fall within one entry (for future absolute-path tools; workspace-scoped tools are always permitted).

### Multi-agent coordination (`claw/coordination/`)
See `docs/tutorials/01-multi-agent-setup.md` for a full walkthrough.
- **Enabled** via `[coordination] enabled = true` in `claw.toml`. Disabled by default.
- `AgentDispatcher.dispatch(HandoffRequest)` — runs an inner turn on the target agent via `ClawGateway.run_agent_turn()`. Session-persistent when `HandoffRequest.session_key` is set; stateless otherwise. No channel delivery. Emits `claw.delegation.started` / `claw.delegation.complete` / `claw.delegation.error` AINDY events (fire-and-forget) when `_aindy` is set and `emit_events=True`. Unknown-agent short-circuit returns error immediately with no events fired.
- `run_agent_turn(agent_id, prompt, context="", session_key="")` on `ClawGateway` — builds the target agent's full system prompt (workspace + skills + memories + knowledge), runs one turn, returns response text. When `session_key` is provided, uses `ClawSessionManager` (lock + compact + prune pipeline) so history accumulates across calls. When empty, stateless (Phase 8 behavior). Returns `"[error: ...]"` on failure.
- `delegate_to_agent` tool: LLM calls with `agent_id` (target) + `prompt` + optional `context`. `_agent_id` and `_session_key` (calling agent + caller session) injected by `scoped_executor`. Handler derives delegation key `delegate:{from}:{caller_session}:{to}` and passes it as `HandoffRequest.session_key`. Registered in `startup()` when `coordination.enabled = true`.
- `is_coordination_tool(name)` — returns True for `delegate_to_agent`; used by `scoped_executor` injection check.
- **Cross-agent memory**: `cross_agent_memory = ["agentA"]` on `[[agents.list]]` causes `_run_turn` to also recall memories from `agentA`'s namespace (up to 3 per source agent).
- **Per-agent skill gating**: `capabilities.skill_use.allow/deny` on `[[agents.list]]` is applied as a second `SkillGate` pass after the global gate. `["*"]` in the allow list means "all skills" (wildcard).
- `HandoffResult.success` is `False` when response starts with `"[error:"`. Caller sees the error string in `.error`.

### Weave layer (`claw/weave/`)
See `docs/tutorials/03-connecting-weave-nodes.md` for peer setup. REST endpoints are documented in `docs/API_REFERENCE.md`.
- **Enabled** via `[weave] enabled = true` in `claw.toml`. Disabled by default.
- `get_or_create_node_id(config_node_id, state_dir)` — returns config value if set; otherwise reads/creates `~/.claw/node_id` (or `<state_dir>/node_id`) as a persistent UUID.
- `WeaveNodeStore(db_path)` — SQLite registry (`weave_nodes` table). `":memory:"` for tests. Methods: `register()`, `get()`, `list_nodes()`, `remove()`, `close()`. `register()` is `INSERT OR REPLACE` (upsert).
- `WeaveClient(local_node_id, timeout=10.0)` — `httpx.AsyncClient` for cross-node calls. Phase 12 methods: `ping`, `list_agents`, `delegate`, `register_self`. Phase 13 additions: `fetch_documents`, `fetch_document` (returns `None` on 404), `fetch_tasks`. Phase 14 additions: `list_all_agents` (concurrent `asyncio.gather` across all nodes; skips failures), `create_document`, `create_task`, `update_task` (returns `None` on 404), `search_knowledge`. All methods swallow exceptions and return safe defaults; never raise.
- **Tools** (`claw/weave/tools.py`): 11 tools total — `weave_delegate`, `weave_list_nodes`, `weave_list_agents` (Phase 12); `weave_list_workspace_documents`, `weave_read_document`, `weave_list_workspace_tasks` (Phase 13); `weave_discover_agents`, `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge` (Phase 14). Registered via `register_weave_tools()` in `startup()`. `_session_key` injected by `scoped_executor`; `weave_delegate` derives `weave:{from_node}:{caller_session}:{to_node}:{agent_id}` as the cross-node session key.
- `is_weave_tool(name)` — True for all 11 weave tools; used by `scoped_executor`/`_inner_exec` injection check (same pattern as `is_memory_tool` etc.).
- **REST endpoints** in `_build_claw_router` (only when `config.weave.enabled`):
  - `GET /weave/agents` — returns `{node_id, agents: [{agent_id, name}]}`
  - `GET /weave/nodes` — returns registered peer list
  - `POST /weave/nodes/register` — body: `WeaveRegisterRequest`; persists peer in `WeaveNodeStore`
  - `POST /weave/delegate` — body: `WeaveDelegateRequest`; calls `run_agent_turn(agent_id, prompt, ..., session_key=req.session_key)` and returns response
- `ClawGateway` attributes: `weave_store: Optional[WeaveNodeStore]`, `weave_client: Optional[WeaveClient]`, `_weave_node_id: str`, `weave_node_id` property.
- CLI: `claw weave status/nodes/connect/disconnect` (requires `weave.enabled = true`).
- **Cross-node workspace federation** (Phase 13) — pull-on-read, peer-trust model:
  - `WeaveClient`: `fetch_documents(node, agent_id)`, `fetch_document(node, agent_id, doc_id) -> dict|None`, `fetch_tasks(node, agent_id, status="")`
  - Tools: `weave_list_workspace_documents`, `weave_read_document`, `weave_list_workspace_tasks` — same injection pattern via `is_weave_tool`
  - REST (requires both `weave.enabled` AND `workspace.enabled`): `GET /weave/workspace/{agent_id}/documents`, `GET /weave/workspace/{agent_id}/documents/{doc_id}`, `GET /weave/workspace/{agent_id}/tasks?status=...`
  - `fetch_document` returns `None` on 404 (not an error string); tool handler converts `None` → `{"error": "..."}` JSON
  - Document endpoint verifies `doc.workspace_id == agent_id` before returning — prevents cross-workspace leakage via guessed doc IDs
- **Weave-wide agent discovery and cross-node writes** (Phase 14):
  - `WeaveClient.list_all_agents(nodes)` — `asyncio.gather(..., return_exceptions=True)` across all nodes; `isinstance(agents, list)` filters out exceptions; adds `node_id` + `node_url` attribution to each entry
  - `WeaveClient`: `create_document`, `create_task`, `update_task` (returns `None` on 404), `search_knowledge`
  - Tools: `weave_discover_agents` (no required params — queries all registered nodes), `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge`
  - REST write endpoints (gated on `workspace.enabled`): `POST /weave/workspace/{agent_id}/documents`, `POST /weave/workspace/{agent_id}/tasks`, `PATCH /weave/workspace/{agent_id}/tasks/{task_id}` — use `WeaveCreateDocumentRequest`, `WeaveCreateTaskRequest`, `WeaveUpdateTaskRequest` models
  - Knowledge endpoint (gated on `knowledge.enabled`): `GET /weave/workspace/{agent_id}/knowledge?q=...&limit=...` — calls `gateway.knowledge_index.search()` directly via `asyncio.to_thread` (NOT `knowledge_retriever.retrieve()`, which has no per-call `limit` param); serializes `Chunk` dataclass via `dataclasses.asdict()`

### Knowledge watcher (`claw/knowledge/watcher.py`)
- `KnowledgeWatcher.watch(agents)` is a background coroutine started in `ClawGateway.startup()` when knowledge is enabled.
- Requires `watchfiles` (already in venv); exits gracefully with a log message if not installed.
- On file create/modify: calls `clear_source()` then `ingest_file()` then `upsert_many()` — same pipeline as the startup scan.
- On file delete: calls `clear_source()` only.
- Excludes `ALL_WORKSPACE_FILES` (identity/boot docs) and unsupported extensions — same exclusion rules as `WorkspaceScanner`.
- Cancelled via `_listener_tasks["knowledge-watcher"]` in `ClawGateway.shutdown()`.

### AINDY bridge (`claw/aindy/client.py`)
- `_AsyncAINDYClient` wraps `aindy_sdk.AINDYClient` (sync, stdlib urllib) via `asyncio.to_thread()`.
- Three gates prevent AINDY unavailability from ever blocking a turn:
  1. `self._aindy is None` — client not constructed (disabled or no api_key)
  2. `if self._aindy and self.config.aindy.emit_events:` at each call site
  3. `except Exception: pass` inside `_emit_aindy()` helper
- Events are `asyncio.create_task()` (fire-and-forget): `sys.v1.claw.turn.start`, `sys.v1.claw.turn.complete`, `sys.v1.claw.turn.error`, `claw.session.started`, `claw.session.ended`, `claw.memory.written`, `claw.cron.executed`
- Default config: `[aindy] enabled = false` in `claw.toml`. Enable via `AINDY_API_KEY` + `AINDY_URL` env vars or `claw.toml`.
- `AINDYConfig` fields: `enabled`, `url`, `api_key`, `emit_events`, `memory_backend` (`"local"`/`"aindy"`/`"aindy-fallback"`), `user_id` (MAS namespace root), `mounted` (bypass auth + skip health routes when running inside AINDY platform layer).
- **Mounted mode** (`aindy.mounted = true`): `GatewayAuth(bypass=True)` skips all auth; `/health` and `/ready` are omitted from the app; use `register_claw_app()` in `claw/aindy/app_registration.py` as the entry point instead of `claw start`.
- `AINDY.platform_layer.registry.register_router(router)` signature: `(router, *, root=False, legacy_root=False)` — **no `prefix` parameter**; prefix is applied by the platform layer caller.

### ConversationalTurn (agents/turn.py)
- Uses `nodus_llm.CredentialStore` for key rotation, but calls `anthropic.AsyncAnthropic` directly for streaming + tool use.
- Nodus session injects a `timestamp` field into messages — strip everything except `role` and `content` before passing to Anthropic, or the API rejects the request.

## Hard-won gotchas

| Gotcha | Fix |
|--------|-----|
| `AgentsConfig.agents` field | Uses `alias="list"` because `list` as a field name shadows the Python builtin. TOML key is `[[agents.list]]`. |
| `StaticFiles` / Prometheus crash | Do **not** use `app.mount()` for the webchat UI. Serve `index.html` as `FileResponse`. `prometheus_fastapi_instrumentator` crashes on `_IncludedRouter`. |
| `ToolRegistry` dedup | `register()` silently skips duplicate tool names — safe to call multiple times. |
| `KeyRing` constructor | `KeyRing(active=secret)` — `active` is a required positional keyword arg. |
| `PairingStore` codes | Single-use; `approve()` returns `None` if code was already consumed. |
| Windows date format | `%-d` (Linux strftime) does not work on Windows. Use `.format(day=now.day)` instead. |
| Daemon mode | Double-fork (`os.fork()`) is POSIX only. On Windows, print a graceful error and exit. |
| `pytest-asyncio` mode | `asyncio_mode = "auto"` is set in `[tool.pytest.ini_options]` in `pyproject.toml`. Do not add `@pytest.mark.asyncio` to tests — it's unnecessary and was removed. |
| Memory tests | Always pass `db_path=":memory:"` in test configs. Empty string hits the real `~/.claw/memory.db` and leaks state between test runs. |
| `nodus-lang` 4.0.4+ | Fixed `session_id` propagation to child VMs and retry trace bleed to stderr. Do not downgrade below 4.0.4. |
| `_IncludedRouter` has no `.path` | `app.include_router()` wraps routes in `_IncludedRouter` which has no `.path` attribute. To collect all route paths: recursively walk `r.original_router.routes` for any route where `getattr(r, 'path', None) is None`. |
| Windows `→` encoding | The `→` character causes `UnicodeEncodeError` (cp1252) in print statements on Windows. Use `->` in all print/log strings. |
| `→` in test output | Same cp1252 issue applies in test scripts. Use `replace_all=True` to fix all occurrences at once. |
| FTS5 DELETE | FTS5 virtual tables support `DELETE FROM fts WHERE rowid = ?` but NOT `DELETE WHERE col = ?` for non-rowid columns. Store `fts_rowid` in the base table and delete by rowid. |
| FTS5 rank ordering | `ORDER BY rank` in FTS5 returns best matches first (rank is BM25, negative values; more negative = better match). |
| `ingest_file()` UUIDs | Each call to `ingest_file()` generates fresh `chunk_id` UUIDs. Always call `clear_source()` before re-ingesting a file to avoid phantom FTS5 entries. |
| `WorkspaceScanner` scope | Scans top-level of workspace dir only (non-recursive). Excludes `ALL_WORKSPACE_FILES` and files with unsupported extensions. |
| `WorkspaceStore` home workspace | Each agent's home workspace uses `id == agent_id`. `create_workspace()` uses `INSERT OR IGNORE` — safe to call twice. Use `ensure_workspace()` on manager to get-or-create. |
| `WorkspaceStore` upsert by name | `upsert_document()` matches on `(workspace_id, name)` — same name replaces body. The original `id` is preserved (returned in result). |
| Workspace tools scope | By default `ws_*` tools operate on the calling agent's home workspace. Pass `target_agent_id` on `ws_create_task`, `ws_list_tasks`, `ws_create_document`, `ws_list_documents` to access another agent's workspace (requires an explicit permission grant). `ws_get_document` and `ws_update_task` infer the workspace from the object ID and check permission automatically. |
| `WorkspaceConfig.db_path` | `":memory:"` for tests (same pattern as `MemoryConfig`). Empty string → `~/.claw/workspace.db`. |
| `CapabilitySet` import in schema.py | `schema.py` imports `CapabilitySet` from `claw.permissions.model`. This is safe: `permissions/model.py` only imports pydantic. No circular dependency. |
| `PermissionEnforcer` is per-turn | The enforcer is created fresh in `_run_turn` from the current agent config — not stored on the gateway. Capabilities can change without restart if config is reloaded. |
| `filter_tool_definitions` before LLM | Always call this BEFORE `turn.run()` — the filtered list is what the LLM sees. Denied tools are not presented; the LLM can never request them. |
| Private network block is unconditional | `browser_fetch` always blocks RFC-1918 + loopback regardless of `external_http` config. There is no config switch to allow private network access. |
| `PermissionDenied` returns JSON error | `scoped_executor` catches `PermissionDenied` and returns `json.dumps({"error": "permission denied: ..."})` — the LLM sees a tool result, not an exception. |
| `KnowledgeWatcher` uses `_listener_tasks` | The watcher asyncio task is stored in `_listener_tasks["knowledge-watcher"]` so it is automatically cancelled by `shutdown()` with all other listener tasks. |
| `skill_use` capability wired (Phase 8) | `CapabilitySet.skill_use.allow/deny` is now applied as a second `SkillGate` pass in `_run_turn` after the global gate. `SkillGate` treats `["*"]` in allow as "all skills" (wildcard); empty allow also means all. |
| `filesystem.paths` only active when `fs.read/write = True` | `_check_filesystem` early-returns (allows) when `fs.read = False` — workspace tools always pass through. Path-scope validation only runs when read/write is explicitly `True` AND paths are set. This means `filesystem.paths` has no effect on current workspace-scoped tools; it is reserved for future absolute-path tools. |
| `delegate_to_agent` session persistence | `scoped_executor` injects `_session_key` (the caller's session key) alongside `_agent_id`. The handler derives `delegate:{from}:{caller_session}:{to}` and passes it as `HandoffRequest.session_key` → `run_agent_turn()`. When `_session_key` is empty (no caller session), delegation remains stateless. |
| `run_agent_turn` session branch | When `session_key` is non-empty, the method acquires `lock_for(session_key)`, appends user message, runs compact + prune, calls `turn.run(messages=...)` with history, then appends the assistant response. Outside the lock, stateless path passes `[{"role": "user", ...}]` only. |
| `is_coordination_tool` must be imported in scoped_executor | `_run_turn` imports `is_coordination_tool` inline (same as `is_memory_tool`/`is_workspace_tool`) to inject `_agent_id` + `_session_key` for `delegate_to_agent`. Without this injection the handler receives no `_agent_id` and `from_agent` defaults to `"unknown"`. |
| Delegation audit events (Phase 11) | `AgentDispatcher` fires `claw.delegation.started`, `claw.delegation.complete`, `claw.delegation.error` via `asyncio.create_task` (fire-and-forget, same pattern as turn events in `server.py`). Unknown-agent path fires no events. `delegation_id` UUID ties started/complete/error together in the AINDY audit log. `_emit_event` helper in `dispatcher.py` swallows all exceptions — AINDY unavailability never blocks a delegation. |
| Weave `node_id` persistence | `get_or_create_node_id("", state_dir)` writes `<state_dir>/node_id` on first call and returns the same UUID thereafter. Config `weave.node_id` takes precedence when set. |
| `WeaveNodeStore` is sync SQLite | Same pattern as `MemorySqliteStore` and `WorkspaceStore`. Pass `":memory:"` in tests. Empty `db_path` resolves to `~/.claw/weave.db`. |
| Weave tools injected same as coordination | `is_weave_tool(name)` is imported inline in both `scoped_executor` and `_inner_exec`; they both check `or is_weave_tool(name)` so `_agent_id`, `_execution_unit_id`, `_session_key` are injected. The `weave_delegate` handler extracts `_session_key` to build the cross-node session key `weave:{from_node}:{caller_session}:{to_node}:{agent_id}`. |
| Weave REST endpoints conditional | All `/weave/*` routes are only registered inside `if config.weave.enabled:` in `_build_claw_router`. When disabled, the block is skipped entirely. |
| `WeaveClient` never raises | All `WeaveClient` methods catch `Exception` and return `False` / `[]` / `"[error:...]"` — network failures never propagate to the LLM tool call. |
| `claw weave connect` requires live remote | `connect` always calls `GET /weave/agents` on the remote to fetch its `node_id`. `--no-ping` only skips the subsequent `WeaveClient.ping()` call — it does NOT bypass the node_id fetch. If the remote is unreachable, `connect` will always fail; there is no offline-registration path. |
| Workspace federation double-gate | `/weave/workspace/*` endpoints are only registered when BOTH `config.weave.enabled` AND `config.workspace.enabled` are true. Weave alone is not enough. |
| `fetch_document` vs `delegate` return on failure | `fetch_document` returns `None` (not an error string) when the remote returns 404 or any error. The tool handler converts `None` → `{"error": "..."}` JSON. This differs from `delegate` which returns `"[error:...]"` directly. |
| `knowledge_retriever.retrieve()` has no `limit` param | `KnowledgeRetriever.retrieve(query, workspace_id)` uses `self._top_k` set at construction — no per-call limit. The Weave knowledge endpoint calls `gateway.knowledge_index.search(q, agent_id, limit)` directly via `asyncio.to_thread` to support a caller-supplied limit. |
| `Chunk` is a dataclass, not Pydantic | `Chunk` is decorated with `@dataclass` (in `claw/knowledge/ingestion.py`). Serialize it with `dataclasses.asdict(c)`, NOT `.model_dump()`. Using `.model_dump()` will raise `AttributeError`. |
| `list_all_agents` skip-failed-nodes pattern | `asyncio.gather(..., return_exceptions=True)` returns exceptions as values in the results list. Check `isinstance(agents, list)` (not `not isinstance(agents, Exception)`) to filter them out — a failed node yields an `Exception` object, not a list. |

## Package layout

```
claw/                   core package
claw/aindy/             AINDY bridge: client.py, memory_store.py, app_registration.py
claw/coordination/      Multi-agent coordination: model.py, dispatcher.py, tools.py
claw/weave/             Distributed Weave layer: model.py, registry.py, client.py, tools.py
claw/knowledge/         Knowledge layer: ingestion.py, index.py, retrieval.py, injector.py, scanner.py, watcher.py
claw/permissions/       Permissions layer: model.py, enforcer.py
claw/workspace/         Workspace layer: model.py, store.py, manager.py, tools.py, bootstrapper.py, initializer.py
claw/gateway/server.py  ClawGateway + build_app() + _build_claw_router()
claw_discord/           Discord adapter
claw_matrix/            Matrix adapter
claw_signal/            Signal adapter
claw_slack/             Slack adapter
claw_telegram/          Telegram adapter
claw_webchat/           Built-in browser UI + WebSocket adapter
workflows/              Nodus DSL scripts (.nd)
tests/                  Milestone test suites (218/218)
skills/                 User skill files (empty by default)
workspace/              Agent workspace placeholder (.gitkeep)
docs/                   Project documentation (see docs/ reference below)
```

`_build_claw_router(gateway, config) -> APIRouter` extracts all Claw-specific routes. `build_app()` gates `/health`, `/ready`, and observability behind `not config.aindy.mounted` then calls `app.include_router(_build_claw_router(...))`.  
`register_claw_app(config_path, prefix)` in `claw/aindy/app_registration.py` is the mounted-mode entry point: starts the gateway, builds the router, calls `AINDY.platform_layer.registry.register_router(router)`, returns the started `ClawGateway`.

## docs/ reference

Operational docs (config, API, deployment, channels, tests, tutorials):

| Document | Covers |
|---|---|
| `docs/CONFIGURATION.md` | Full `claw.toml` schema — every section, key, default, and env var |
| `docs/API_REFERENCE.md` | REST + WebSocket endpoints, auth methods, request/response shapes |
| `docs/DEPLOYMENT.md` | Standalone vs. mounted mode, process management (systemd/NSSM/pm2), nginx TLS, Weave multi-node setup |
| `docs/CHANNELS.md` | Per-adapter setup and config — WebChat, Discord, Telegram, Slack, Matrix, Signal |
| `docs/TEST_STRATEGY.md` | Suite layout (3 generations, 16 files, 218 functions), testing patterns, coverage gaps, guidelines for adding tests |
| `docs/CHANGELOG.md` | Version history; v0.1.0 covers all 14 phases |
| `docs/tutorials/01-multi-agent-setup.md` | Multi-agent coordination walkthrough: delegation, cross-agent memory, channel routing |
| `docs/tutorials/02-knowledge-layer.md` | Knowledge indexing walkthrough: FTS5, retrieval, auto-reindex, chunk tuning |
| `docs/tutorials/03-connecting-weave-nodes.md` | Weave peer setup: cross-node delegation, workspace federation, knowledge search |

Design and architecture docs:

| Document | Covers |
|---|---|
| `docs/CLAW_AINDY_INTEGRATION_PLAN.md` | Authoritative phase-by-phase AINDY integration plan (Phases 1–14 complete) |
| `docs/ROADMAP.md` | Phase completion status; Phase 15 (operational hardening) scoped; Phases 16–20 (public product path) documented; deferred Weave options B/C preserved |
| `docs/ARCHITECTURE.md` | High-level architecture narrative |
| `docs/AGENT_SPEC.md` | Agent identity and capability model |
| `docs/WORKSPACE_SPEC.md` | Workspace object model spec |
| `docs/KNOWLEDGE_MODEL.md` | Knowledge layer design |
| `docs/PERMISSIONS_AND_SECURITY.md` | Security model and permissions design |
| `docs/RUNTIME_CONTRACT.md` | Gateway/turn contract |
| `docs/DECISIONS.md` | Architecture decision records |
| `docs/ONBOARDING.md` | First-time setup guide |
| `docs/OPENCLAW_NODUS_ARCHITECTURE.md` | OpenClaw to Nodus migration context |

## Nodus DSL (`workflows/*.nd`)

**nodus-lang 4.0.6** — `pip install nodus-lang`. Bytecode version 4.

```powershell
venv\Scripts\nodus.exe run workflows/boot.nd
venv\Scripts\nodus.exe run --time-limit 5000 workflows/boot.nd  # workflows or anything with sleep
venv\Scripts\nodus.exe check workflows/boot.nd                  # syntax check
venv\Scripts\nodus.exe fmt workflows/boot.nd                    # format in place
```

### Critical rules — never violate

**Types and access**
- `{k: v}` is a **record** — dot access: `r.key`
- `{"k": v}` is a **map** — bracket access: `m["key"]`
- Never mix. `json.parse()` returns a map — always bracket access.
- `run_workflow()` / `run_goal()` return maps: `r["steps"]["step_name"]`, `r["state"]["key"]`

**Operators and syntax**
- `+=`, `-=`, `*=`, `/=` work. `**` does not — use `math.pow()`.
- `print()` is single-argument. Use interpolation: `print("val: \(x)")`.
- Expressions cannot span newlines. Keep list literals and function calls on one line.

**Numbers**
- Bare numbers are floats: `42` → `type()` = `"float"`. Use `i` suffix for integers: `42i`.
- Use integers for counters, indices, loop bounds, and workflow state.

**Imports**
- All imports must be at the top level — never inside functions, steps, or conditionals.

**Closures and mutable state**
- Assigning to an outer `let` inside a closure creates a nil local shadow, not a mutation.
- Use a map for shared mutable state: `let s = {"n": 0i}` then `s["n"] = s["n"] + 1i`.

**Coroutines and channels**
- `spawn()` takes a coroutine value, not a function literal.
  Pattern: `let c = coroutine(fn() { ... })` → `spawn(c)` → `run_loop()`.
- Channels are VM built-ins — `channel()`, `send()`, `recv()`, `close()`. Do not `import "std:channel"`.
- Default execution deadline is 200ms wall-clock (including sleep). Override: `--time-limit N`.

**Workflows**
- `checkpoint` is valid inside step bodies only, not at workflow body level.
- Step results must be JSON-serializable — return maps `{"k": v}`, not records `{k: v}`.

### Skill

Full Nodus skill is at `.claude/commands/nodus.skill` — loaded automatically by Claude Code.
Sub-references: `.claude/commands/nodus/` (quickstart, errors, examples, idioms, modules).

---

## AINDY runtime reference (installed in venv)

- `aindy_sdk.AINDYClient` — sync stdlib urllib; sub-APIs: `.events`, `.memory`, `.flows`, `.executions`, `.nodus`, `.sandbox`, `.syscalls`
- `AINDY.kernel.SyscallDispatcher` — 10-step pipeline; never raises; all errors in envelope
- `AINDY.kernel.SyscallRegistry` — flat (`sys.v1.memory.read`) + versioned access; 17 built-ins; `DEFAULT_NODUS_CAPABILITIES = ["memory.read","memory.write","memory.search","event.emit"]`
- MAS path convention: `/memory/{tenant_id}/{namespace}/{addr_type}/{node_id}`; wildcards `/*` (one level), `/**` (recursive)
- EXACTLY_ONCE idempotency: `EffectRecord` table + SHA-256; concurrent pending degrades to AT_LEAST_ONCE with warning
- `validate_nodus_source()` in `nodus_security.py` — blocks Python `import`, `eval`, `exec`; 12,000 char limit

## Integration plan

`docs/CLAW_AINDY_INTEGRATION_PLAN.md` is the authoritative phase-by-phase migration plan.

**Phases 1–14 are complete (including Phase 6 follow-ons):**
- Phase 1: SDK wiring + lifespan + turn lifecycle events
- Phase 2: AINDY memory backend (`AINDYMemoryStore`, `_aindy_or_local`, `memory_backend` config)
- Phase 3: Execution tracking — `execution_unit_id` per turn, `claw.session.*` / `claw.memory.written` / `claw.cron.executed` events
- Phase 4: Gateway mount — `_build_claw_router()`, `build_app()` dual-mode, `GatewayAuth(bypass=True)`, `register_claw_app()`
- Phase 5: Knowledge layer — `claw/knowledge/` package, SQLite FTS5 index, workspace scanner, retriever, injector, `claw workspace index` CLI
- Phase 6: Workspace objects — `WorkspaceStore`, `WorkspaceManager`, Documents/Tasks/Assets/Permissions, 6 agent tools, CLI `create`/`list`/`share`
- Phase 6 follow-ons: `KnowledgeWatcher` — `watchfiles`-based background auto-reindex on workspace file changes
- Phase 7: Permissions layer — `claw/permissions/` package, `CapabilitySet` config model on `AgentConfig`, `PermissionEnforcer` (tool allow/deny, HTTP enforcement, private network block)
- Phase 8: Multi-agent coordination — `claw/coordination/` package, `AgentDispatcher`, `delegate_to_agent` tool, `run_agent_turn()`, per-agent skill gating (`skill_use`), cross-agent memory recall
- Phase 9: Cross-workspace tool access — `target_agent_id` on `ws_*` list/create tools; implicit permission check on `ws_get_document`/`ws_update_task` via object `workspace_id`
- Phase 10: Session-persistent delegation — `run_agent_turn(session_key=...)`, delegation session key derivation in `delegate_to_agent` handler, `_session_key` injection in `scoped_executor` and `_inner_exec`, `HandoffRequest.session_key` field
- Phase 11: Delegation audit trail — `AgentDispatcher` emits `claw.delegation.started` / `claw.delegation.complete` / `claw.delegation.error` via `asyncio.create_task` (fire-and-forget); `delegation_id` UUID per dispatch for correlation; `persistent` flag in payload
- Phase 12: Distributed Workspaces (Weave) — `claw/weave/` package; `WeaveNodeStore` (SQLite peer registry); `WeaveClient` (httpx cross-node HTTP); `weave_delegate` / `weave_list_nodes` / `weave_list_agents` tools; `WeaveConfig` in `ClawConfig`; `/weave/*` REST endpoints in `_build_claw_router`; `claw weave` CLI; `is_weave_tool` injection in `scoped_executor` and `_inner_exec`
- Phase 13: Cross-node workspace federation — pull-on-read, peer-trust model; `WeaveClient.fetch_documents/fetch_document/fetch_tasks`; `weave_list_workspace_documents` / `weave_read_document` / `weave_list_workspace_tasks` tools; `GET /weave/workspace/{agent_id}/documents[/{doc_id}]` + `GET /weave/workspace/{agent_id}/tasks` REST endpoints (gated on both `weave.enabled` and `workspace.enabled`)
- Phase 14: Weave-wide agent discovery + cross-node writes — `WeaveClient.list_all_agents` (concurrent, skip-failed-nodes); `create_document`, `create_task`, `update_task`, `search_knowledge`; 5 new tools (`weave_discover_agents`, `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge`); write REST endpoints (`POST /weave/workspace/{agent_id}/documents|tasks`, `PATCH /weave/workspace/{agent_id}/tasks/{task_id}`); knowledge REST endpoint (`GET /weave/workspace/{agent_id}/knowledge`; uses `index.search()` directly, serializes `Chunk` via `dataclasses.asdict()`)

Phase 15+ (workspace data replication, Weave-wide knowledge federation) are on the roadmap.
