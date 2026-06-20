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

---

## Planned

### Phase 6 — Workspace as First-Class Object
*Workspaces become explicit, shareable, multi-agent containers*

**Capabilities unlocked:**
- Multiple agents operating inside one workspace with role-based access
- Workspace objects: Documents, Memories, Tasks, Assets with stable IDs
- Relationship graph: typed edges between workspace objects
- Workspace sharing: another Claw instance (or Weave node) can mount a read-only workspace

**Work:**
- `claw/workspace/model.py` — `Workspace`, `Document`, `Task`, `Asset` data models
- AINDY MAS as the workspace object store (beyond just memory nodes)
- `claw workspace create / list / share` CLI commands
- Per-agent workspace permissions (read/write/none per object type)
- Cross-workspace references (Phase 6.5)

### Phase 7 — Permissions and Filesystem Access
*Agents can access the real filesystem — safely*

**Capabilities unlocked:**
- Agents can read files outside the workspace directory (with explicit grant)
- Write and delete access available under declared `paths`
- Capability declaration in `claw.toml` per agent (full model from `PERMISSIONS_AND_SECURITY.md`)
- Tool allowlist/denylist per agent enforced at runtime (not just skills)
- Private network block for `browser_fetch`

**Work:**
- `claw/permissions/model.py` — `CapabilitySet`, `FilesystemPermission`, `HttpPermission`
- `claw/permissions/enforcer.py` — validates tool calls against declared capabilities at invocation time
- Path validation and traversal protection
- URL denylist for internal networks
- Config schema: `[agents.list.capabilities]`

### Phase 8 — Multi-Agent Coordination
*Agents collaborate inside a workspace*

**Capabilities unlocked:**
- One agent can hand off a task to a specialized agent
- Agents share workspace knowledge but have isolated memory and sessions
- A coordinator agent can spawn sub-agents for parallel execution
- Cross-agent message passing via AINDY event bus

**Work:**
- Agent handoff protocol (Nodus DSL + AINDY event bus)
- `claw/coordination/` — handoff, delegation, result aggregation
- Cross-agent memory read (opt-in, declared in config)
- Coordinator pattern: planner agent + executor agents
- AINDY MAS as shared coordination state store

### Phase 9 — Distributed Workspaces
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
