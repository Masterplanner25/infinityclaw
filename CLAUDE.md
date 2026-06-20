# Infinity Claw — Claude Code context

## Project identity

**Infinity Claw** (`claw` package, `C:\dev\claw`) is the first agent built on the Masterplan Infinite Weave Framework. It showcases the Nodus Language Ecosystem (nodus-lang 4.0.5, 29-package runtime) integrated with the AINDY execution kernel (aindy-runtime 1.4.0) as a production-grade personal AI assistant.

- GitHub: https://github.com/Masterplanner25/infinityclaw
- Package version: 0.1.0
- Python: 3.11+ (venv at `C:\dev\claw\venv`)
- Tests: `pytest tests/ -q` → 72/72 (never break this baseline)

## How to run

```powershell
venv\Scripts\python.exe -m claw start          # gateway at http://127.0.0.1:18789/
venv\Scripts\python.exe -m pytest tests/ -q    # test suite
venv\Scripts\python.exe -m claw doctor         # subsystem health check
venv\Scripts\python.exe -m claw workspace index  # re-index workspace files (requires knowledge.enabled = true)
```

## Architecture overview

```
claw/gateway/server.py   ClawGateway + build_app()
  ├── AgentRegistry      credential store, ConversationalTurn per agent
  ├── ClawSessionManager asyncio.Lock per session key; compaction + pruning
  ├── ChannelAdapterRegistry  WebChat + external adapters
  ├── BindingResolver    channel/peer → agent_id routing
  ├── SkillLoader/Gate   file-based skills with allow/deny
  ├── MemoryManager      SQLite recall + injection
  ├── ToolRegistry       shared tool defs; scoped_executor injects agent_id
  ├── CronManager        APScheduler cron jobs
  ├── AuthManager        JWT issuance + SqliteApiKeyStore
  ├── KnowledgeIndex     SQLite FTS5 workspace knowledge index (optional)
  ├── KnowledgeRetriever async retrieval wrapper; top-K chunks per turn
  ├── KnowledgeInjector  formats chunks into ## Relevant Knowledge prompt block
  └── _AsyncAINDYClient  optional AINDY bridge (claw/aindy/client.py)
```

`build_app(cfg)` returns `(FastAPI, ClawGateway)` — this signature is test-critical, do not change it.

The FastAPI app uses a `lifespan` context manager (not `@app.on_event`, which is deprecated and was removed in the Phase 1 AINDY work).

## Key subsystems

### Turn pipeline (`_run_turn` in server.py)
1. Detect `is_new_session` (empty history check — must happen **before** appending the user message)
2. Generate `execution_unit_id = str(uuid.uuid4())` — threads through memory writes, AINDY events, tool calls
3. Load workspace files + skills + recall memories + retrieve knowledge chunks (if enabled)
4. Build system prompt via `PromptContext` (order: identity files → runtime → boot files → memories → knowledge → skills)
5. Append user message; compact if needed; prune
6. Fire AINDY events: `claw.session.started` if new session, `sys.v1.claw.turn.start` (both fire-and-forget, skipped if AINDY disabled)
7. `await turn.run(...)` via `scoped_executor` which injects both `agent_id` **and** `execution_unit_id` — streams chunks to WebChat or collects for other channels
8. Append assistant message; deliver response
9. Fire AINDY `turn.complete` or `turn.error` event

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
- **Enabled** via `[knowledge] enabled = true` in `claw.toml`. Disabled by default.
- `WorkspaceScanner` finds files in the agent workspace directory that are NOT in `ALL_WORKSPACE_FILES` (identity/boot files) and have a supported extension.
- `ingest_file(path, workspace_id, chunk_size, chunk_overlap)` parses + chunks a file into `Chunk` objects (UUID chunk_id generated fresh each call).
- `KnowledgeIndex` — two-table SQLite schema: `knowledge_chunks` (metadata + `fts_rowid` FK) + `knowledge_fts` (FTS5 virtual table). `clear_source()` deletes FTS5 entries by rowid before deleting from base table.
- `KnowledgeRetriever.retrieve()` is async (wraps `index.search()` via `asyncio.to_thread`). FTS5 query uses OR of extracted words; rank is BM25 (lower/more negative = better match).
- `KnowledgeInjector.build_block()` formats a `## Relevant Knowledge` section for the system prompt.
- Startup scan: on `ClawGateway.startup()`, all workspace files (per agent) are scanned and indexed.
- `claw workspace index [--agent ID]` CLI command re-indexes on demand.
- `PromptContext.knowledge_block` injected between memories and skills in `SystemPromptBuilder`.

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

## Package layout

```
claw/                   core package
claw/aindy/             AINDY bridge: client.py, memory_store.py, app_registration.py
claw/knowledge/         Knowledge layer: ingestion.py, index.py, retrieval.py, injector.py, scanner.py
claw/gateway/server.py  ClawGateway + build_app() + _build_claw_router()
claw_discord/           Discord adapter
claw_matrix/            Matrix adapter
claw_signal/            Signal adapter
claw_slack/             Slack adapter
claw_telegram/          Telegram adapter
claw_webchat/           Built-in browser UI + WebSocket adapter
workflows/              Nodus DSL scripts (.nd)
tests/                  Milestone test suites (72/72)
skills/                 User skill files (empty by default)
workspace/              Agent workspace placeholder (.gitkeep)
```

`_build_claw_router(gateway, config) -> APIRouter` extracts all Claw-specific routes. `build_app()` gates `/health`, `/ready`, and observability behind `not config.aindy.mounted` then calls `app.include_router(_build_claw_router(...))`.  
`register_claw_app(config_path, prefix)` in `claw/aindy/app_registration.py` is the mounted-mode entry point: starts the gateway, builds the router, calls `AINDY.platform_layer.registry.register_router(router)`, returns the started `ClawGateway`.

## AINDY runtime reference (installed in venv)

- `aindy_sdk.AINDYClient` — sync stdlib urllib; sub-APIs: `.events`, `.memory`, `.flows`, `.executions`, `.nodus`, `.sandbox`, `.syscalls`
- `AINDY.kernel.SyscallDispatcher` — 10-step pipeline; never raises; all errors in envelope
- `AINDY.kernel.SyscallRegistry` — flat (`sys.v1.memory.read`) + versioned access; 17 built-ins; `DEFAULT_NODUS_CAPABILITIES = ["memory.read","memory.write","memory.search","event.emit"]`
- MAS path convention: `/memory/{tenant_id}/{namespace}/{addr_type}/{node_id}`; wildcards `/*` (one level), `/**` (recursive)
- EXACTLY_ONCE idempotency: `EffectRecord` table + SHA-256; concurrent pending degrades to AT_LEAST_ONCE with warning
- `validate_nodus_source()` in `nodus_security.py` — blocks Python `import`, `eval`, `exec`; 12,000 char limit

## Integration plan

`CLAW_AINDY_INTEGRATION_PLAN.md` in the repo root is the authoritative phase-by-phase migration plan.

**Phases 1–5 are complete:**
- Phase 1: SDK wiring + lifespan + turn lifecycle events
- Phase 2: AINDY memory backend (`AINDYMemoryStore`, `_aindy_or_local`, `memory_backend` config)
- Phase 3: Execution tracking — `execution_unit_id` per turn, `claw.session.*` / `claw.memory.written` / `claw.cron.executed` events
- Phase 4: Gateway mount — `_build_claw_router()`, `build_app()` dual-mode, `GatewayAuth(bypass=True)`, `register_claw_app()`
- Phase 5: Knowledge layer — `claw/knowledge/` package, SQLite FTS5 index, workspace scanner, retriever, injector, `claw workspace index` CLI

Phases 6+ (workspace as first-class object, permissions, multi-agent, distributed Weave) are on the roadmap.
