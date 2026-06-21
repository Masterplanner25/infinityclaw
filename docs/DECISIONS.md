# Architecture Decision Records — Infinity Claw

Architecture Decision Records (ADRs) document the significant choices made during development: what was decided, why, and what alternatives were rejected. They are written once and rarely changed.

---

## ADR-001 — Nodus Language Ecosystem as the Orchestration Layer

**Status:** Accepted

**Decision:** Infinity Claw is built on the Nodus Language Ecosystem (nodus-lang 4.0.5, 29-package runtime) rather than a general-purpose Python framework.

**Reason:** Nodus was designed specifically for agentic orchestration: typed session management, credential rotation, prompt context building, and streaming tool use. Using a general framework would require rebuilding what Nodus already provides correctly. Claw is the first Masterplan Infinite Weave application; it must demonstrate that Nodus is production-capable as the orchestration foundation.

**Trade-off:** Nodus is not a public framework. Claw has a hard dependency on a private ecosystem. This is intentional — Claw is a reference implementation, not a standalone open-source project.

---

## ADR-002 — Direct `anthropic.AsyncAnthropic` for Streaming

**Status:** Accepted

**Decision:** `ConversationalTurn` calls `anthropic.AsyncAnthropic` directly for streaming and tool use rather than going through a Nodus LLM abstraction layer.

**Reason:** The Nodus LLM layer does not yet expose a streaming + tool use interface that matches the Anthropic SDK's event model. Wrapping it would require a shim that provides no value while adding complexity. The direct SDK call is the correct abstraction boundary for now.

**Consequence:** Model provider is effectively Anthropic-only at the ConversationalTurn level. Credential rotation (multi-key) is handled by Nodus `CredentialStore`; model switching is handled by `AgentConfig.model`; but streaming is Anthropic-specific.

**Revisit:** When Nodus exposes a streaming tool-use interface, migrate `ConversationalTurn` to use it.

---

## ADR-003 — Synchronous `MemoryStore` Protocol, Async AINDY Bridge

**Status:** Accepted

**Decision:** The `nodus_memory.MemoryStore` protocol is entirely synchronous. Rather than making `AINDYMemoryStore` implement this protocol (which would require blocking the event loop), `AINDYMemoryStore` is an async-native class that `MemoryManager` calls directly in its async methods.

**Reason:** AINDY operations are network calls and must be async. Forcing them into a synchronous protocol via `asyncio.run()` would deadlock inside an already-running event loop. The `MemoryStore` protocol is the right abstraction for local SQLite storage; it is the wrong abstraction for async network storage.

**Consequence:** `MemoryManager.recall()`, `list_all()`, `get()`, `forget()` are all async — a breaking change from the original sync interface. Tests that called these synchronously were updated (`asyncio.run()` for sync test functions, `await` for async ones).

---

## ADR-004 — Three-Gate AINDY Failure Isolation

**Status:** Accepted

**Decision:** Three concentric guards prevent AINDY unavailability from ever blocking a turn:

1. `self._aindy is None` — client not constructed
2. `if self._aindy and config.aindy.emit_events:` — gated at call site
3. `except Exception: pass` inside `_emit_aindy()` — fire-and-forget

**Reason:** AINDY is optional infrastructure. An agent assistant that fails to respond because a metrics backend is down is not acceptable. The user experience must be robust even when AINDY is unavailable, misconfigured, or rate-limited.

**Trade-off:** Failures are logged at DEBUG, not ERROR. Operators who expect AINDY to be available may not notice connectivity issues immediately. Mitigation: `claw doctor` actively pings AINDY and reports its status.

---

## ADR-005 — `asyncio.Lock` per Session Key, Not `nodus_queue`

**Status:** Accepted

**Decision:** Session serialization uses `asyncio.Lock` per session key. The `nodus_queue` primitive was considered and rejected.

**Reason:** `nodus_queue` introduces a dependency on the Nodus session VM for what is a simple concurrency primitive. `asyncio.Lock` is stdlib, zero-overhead, and the correct tool for this use case: one lock per key, held for the duration of a turn, released when done.

**Consequence:** Sessions are serialized per key; concurrent sessions across different keys are fully parallel. This is the correct behavior: two users talking to different agents should not wait for each other.

---

## ADR-006 — FileResponse for WebChat UI, Not `app.mount()`

**Status:** Accepted

**Decision:** The WebChat `index.html` is served via `FileResponse`, not via `StaticFiles` mounted with `app.mount()`.

**Reason:** `prometheus_fastapi_instrumentator` crashes on `_IncludedRouter` objects created by `app.mount()`. The crash was traced to the instrumentator iterating routes and encountering the router object. Using `FileResponse` for the single HTML file avoids the issue entirely while adding no meaningful complexity.

**Consequence:** Only `index.html` is served this way. Static assets (JS, CSS) referenced from `index.html` must be inlined or served by a separate static file server if needed.

---

## ADR-007 — `build_app()` Returns `(FastAPI, ClawGateway)` — Immutable Signature

**Status:** Accepted

**Decision:** `build_app(config)` always returns `(FastAPI, ClawGateway)`. This signature is frozen.

**Reason:** The entire test suite — 60+ tests across 6 milestone files — destructures this return value. A signature change would break every test. The test suite is the deployment contract; breaking it for convenience would undermine trust in the baseline.

**Consequence:** Any extension to `build_app()` must be additive (new parameters with defaults) or must go through a new function. The dual-mode behavior (standalone vs. mounted) is handled by `config.aindy.mounted`, not by a different function signature.

---

## ADR-008 — `APIRouter` Extraction for AINDY Mounted Mode

**Status:** Accepted

**Decision:** Phase 4 extracts all Claw-specific routes into `_build_claw_router()` returning an `APIRouter`. `build_app()` calls `app.include_router(_build_claw_router(...))` internally. `register_claw_app()` calls `register_router(router)` for the AINDY platform layer.

**Reason:** The AINDY platform layer needs to register Claw routes into its own FastAPI app without creating a standalone server. Extracting routes into an `APIRouter` enables both modes: `build_app()` for standalone, `register_claw_app()` for mounted.

**Consequence:** `_build_claw_router()` is a private function (underscore prefix). It is exported for use by `app_registration.py` and tests, but it is not a public API. The public API is `build_app()` (standalone) and `register_claw_app()` (mounted).

---

## ADR-009 — `":memory:"` SQLite for All Tests

**Status:** Accepted

**Decision:** All tests that touch memory must pass `db_path=":memory:"` in `MemoryConfig`. Empty string (`""`) resolves to `~/.claw/memory.db` and causes test state to leak into the real database.

**Reason:** Discovered during Phase 2 integration testing. A test that created real memory nodes in `~/.claw/memory.db` caused subsequent tests to fail because they unexpectedly found pre-existing nodes. In-memory SQLite (`":memory:"`) is isolated per test run and never persists.

**Consequence:** This is documented in `CLAUDE.md` as a hard-won gotcha. Test helpers that construct `MemoryManager` must always pass `db_path=":memory:"`.

---

## ADR-010 — Workspaces as Agent-Centric (for Now)

**Status:** Accepted (Revisit in Phase 6)

**Decision:** Today, a "workspace" is implicitly `~/.claw/agents/{agent_id}/workspace/`. There is no explicit workspace object or cross-agent sharing.

**Reason:** The workspace concept was identified late in Phase 1 design. Modeling it explicitly would have delayed the foundation phase without providing immediate value. The implicit model (agent directory = workspace) is sufficient for single-user, single-agent deployments.

**Revisit:** Phase 6 introduces explicit workspace objects, multi-agent sharing, and the workspace relationship graph. At that point this ADR is superseded by the new workspace model.

**Consequence:** `WORKSPACE_SPEC.md` is intentionally forward-looking. The current codebase implements only the "current state" column in its comparison tables.
