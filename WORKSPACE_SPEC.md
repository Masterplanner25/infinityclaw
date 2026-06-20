# Workspace Specification — Infinity Claw

## What Is a Workspace?

A workspace is the primary organizational unit in Infinity Claw. Agents do not float free in an LLM context window — they operate *inside* a workspace. The workspace defines what the agent knows, what it can access, and what persists between sessions.

This is the distinction that separates Infinity Claw from a chatbot:

> A chatbot answers questions.
> An Infinity Claw agent operates inside a workspace.

---

## Workspace Model

```
Workspace
 ├── Identity     (id, name, owner_agent_id, created_at)
 ├── Documents    (DB-backed: id, name, content_type, body — agent-created notes and records)
 ├── Memories     (agent-persisted structured knowledge via MemoryManager)
 ├── Tasks        (tracked work items with lifecycle: open → in_progress → done/cancelled)
 ├── Assets       (references to binary/external artifacts: id, name, content_type, path)
 ├── Agents       (which agents operate in this workspace, with permissions)
 └── Relationships (typed edges between objects — Phase 9+)
```

---

## Workspace Components

### Identity

Every workspace has a stable explicit identity (Phase 6):

```
Workspace
 ├── id:              string    # stable identifier; == agent_id for home workspaces
 ├── name:            string    # human-readable label
 ├── owner_agent_id:  string    # agent that owns and has full access
 ├── description:     string    # optional
 └── created_at:      datetime
```

Each agent automatically gets a home workspace with `id == agent_id`, created via `WorkspaceManager.ensure_workspace()` at gateway startup.

---

### Documents

Documents are named, typed content objects that persist across sessions (Phase 6).

```
Document
 ├── id:           UUID    # stable reference ID
 ├── workspace_id: string
 ├── name:         string  # unique within workspace; upsert-by-name semantics
 ├── content_type: string  # text | markdown | code | json | csv
 ├── body:         string  # full content
 ├── created_at:   datetime
 └── updated_at:   datetime
```

Agents create and update documents via the `ws_create_document` tool. Documents with the same `name` in the same workspace are updated in place (upsert-by-name); the original `id` is preserved.

**Relationship to file-based workspace:** Markdown files in `~/.claw/agents/{agent_id}/workspace/` remain the identity/boot layer (AGENTS.md, SOUL.md, etc.) and the knowledge index source. DB Documents are a separate, agent-managed layer — structured records the agent creates at runtime.

---

### Memories

Memories are agent-generated structured knowledge. Unlike documents (operator-provided files or agent-created DB records), memories are created by the agent *in response to conversations*.

```
Memory Node
 ├── id:            UUID
 ├── agent_id:      string
 ├── content:       string    # natural language description
 ├── node_type:     string    # insight | decision | outcome | failure
 ├── tags:          list[str]
 ├── extra:         dict      # execution_unit_id, source context
 └── created_at:   datetime
```

Memories are recalled semantically at turn time via `MemoryManager.recall()` and injected into the system prompt. Backend: local SQLite or AINDY MAS (configurable via `[aindy] memory_backend`).

---

### Tasks

Tasks are tracked work items with an explicit lifecycle (Phase 6).

```
Task
 ├── id:           UUID
 ├── workspace_id: string
 ├── title:        string
 ├── body:         string    # optional details
 ├── status:       enum      # open | in_progress | done | cancelled
 ├── priority:     int       # higher = more urgent; tasks sorted priority DESC
 ├── created_at:   datetime
 └── updated_at:   datetime
```

Agents create, list, and update tasks via `ws_create_task`, `ws_list_tasks`, and `ws_update_task` tools. Tasks persist across sessions in the workspace SQLite DB.

---

### Assets

Assets are references to binary or non-textual workspace objects: images, data files, exported artifacts (Phase 6).

```
Asset
 ├── id:           UUID
 ├── workspace_id: string
 ├── name:         string
 ├── content_type: string  # binary | image | data | ...
 ├── path:         string  # filesystem path or URL
 ├── size_bytes:   int
 └── created_at:   datetime
```

Assets are registered in the workspace DB to give them stable IDs and metadata. They are not stored in the DB themselves — only their reference.

---

### Agents and Permissions

A workspace declares which agents can access it, with per-agent permission levels (Phase 6).

```
WorkspacePermission
 ├── workspace_id: string
 ├── agent_id:     string
 └── level:        enum    # none | read | write
```

The workspace **owner** always has full read+write access, regardless of explicit permissions. Other agents require an explicit grant via `WorkspaceManager.set_permission()`.

```
claw workspace share <workspace_id> --agent <agent_id> --perm <read|write|none>
```

`can_read()` / `can_write()` are enforced at the manager layer. Cross-workspace tool access is live (Phase 9): pass `target_agent_id` on list/create tools; ID-based tools enforce permissions automatically via the object's `workspace_id`.

---

### Relationships

Typed edges between workspace objects — **not yet implemented (Phase 9+).**

```
Document A --references--> Document B
Memory     --derived-from--> Document C
Task       --produces--> Asset D
```

---

## Workspace Lifecycle

```
Created (explicit via CLI or ensure_workspace())
    ↓
Bootstrapped     ← file-based workspace dir initialized, default identity docs loaded
    ↓
Active           ← agents operating; memories, documents, tasks accumulating in DB
    ↓
Knowledge-indexed  ← file-based docs ingested into FTS5 index (if knowledge.enabled)
    ↓
Archived / Reset   ← session reset, scheduled cleanup
```

---

## Two-Track Content Model

Infinity Claw has two complementary content tracks in a workspace:

| Track | What | Storage | How injected into prompt |
|---|---|---|---|
| **File-based** | Identity/boot docs (AGENTS.md, SOUL.md, etc.) | Filesystem | Verbatim, always |
| **Knowledge index** | Non-identity files in workspace dir | SQLite FTS5 | Top-K chunks, BM25 ranked |
| **DB objects** | Agent-created Documents, Tasks, Assets | SQLite (workspace.db) | Via agent tools (not auto-injected) |
| **Memories** | Agent-learned knowledge | SQLite or AINDY MAS | Semantic recall, top-K |

---

## Workspace Boundaries

A workspace is a **trust boundary**. Objects inside a workspace are visible to agents operating in that workspace (subject to per-agent permissions). Objects outside a workspace are not visible.

- **Data isolation:** Multiple workspaces on the same Claw instance are isolated by default
- **Agent scope:** An agent's home workspace has `id == agent_id`; other workspaces require an explicit permission grant
- **Agent delegation (Phase 8 — complete):** `delegate_to_agent` tool; agents hand off tasks to each other.
- **Session-persistent delegation (Phase 10 — complete):** delegated agents accumulate history within a caller session; `run_agent_turn(session_key=...)` uses `ClawSessionManager`; stateless mode preserved when `session_key` is empty.
- **Cross-workspace tool access (Phase 9 — complete):** `ws_*` tools support `target_agent_id` for cross-agent workspace reads/writes with permission enforcement. AINDY event-bus coordination is Phase 11+.

---

## Current Implementation Summary

| Concept | Status | Notes |
|---|---|---|
| Workspace identity | **Phase 6** — explicit `Workspace` object with stable ID | Home workspace `id == agent_id` |
| File-based documents | **Phase 1** — files in workspace dir, verbatim-injected | Identity/boot files |
| Knowledge index | **Phase 5** — FTS5 chunk retrieval | Non-identity files, top-K at turn time |
| DB Documents | **Phase 6** — first-class objects, agent-created | `ws_create_document` tool |
| Memories | **Phase 1+2** — SQLite or AINDY MAS | `remember`/`recall` tools |
| Tasks | **Phase 6** — first-class objects with lifecycle | `ws_create_task`/`ws_update_task` tools |
| Assets | **Phase 6** — typed DB-backed references | Registered by ID, not stored in DB |
| Agents per workspace | **Phase 6** — `WorkspacePermission` (none/read/write) | Owner always has full access |
| Agent delegation | **Phase 8** — `delegate_to_agent` tool, `AgentDispatcher`, `run_agent_turn()` | Now session-persistent (Phase 10) |
| Cross-agent memory | **Phase 8** — `cross_agent_memory` on `AgentConfig` | Read-only; write isolation preserved |
| Cross-workspace tools | **Phase 9** — `target_agent_id` on `ws_*` tools; ID-based tools check implicitly | Requires explicit permission grant |
| Session-persistent delegation | **Phase 10** — `run_agent_turn(session_key=...)`, delegation key derivation | LLM needs no new params; stateless preserved |
| Relationships | **Phase 11+** — typed edges in knowledge graph | Not yet modeled |
| Embedding-based retrieval | **Phase 11+** — replace FTS5 with pgvector | KnowledgeRetriever interface stable |
