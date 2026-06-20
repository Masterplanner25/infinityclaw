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
 ├── Identity     (id, name, owner)
 ├── Documents    (files, notes, reference material)
 ├── Memories     (agent-persisted structured knowledge)
 ├── Tasks        (tracked work items, outcomes)
 ├── Assets       (images, data, binary artifacts)
 ├── Agents       (which agents operate in this workspace)
 └── Relationships (links between workspace objects)
```

---

## Workspace Components

### Identity

Every workspace has a stable identity:

```
workspace_id: string    # unique identifier
name:         string    # human-readable label
owner:        string    # user_id of the operator
created_at:   datetime
```

Today, the workspace identity is implicit — `agent_id` serves as the workspace namespace. In Phase 5+, workspaces become explicit first-class objects that can be shared across agents.

---

### Documents

Documents are the primary knowledge substrate. A document is any content the agent should be able to reference: notes, project plans, specifications, research, meeting records.

**Current state:** Documents are files in `~/.claw/agents/{agent_id}/workspace/`. They are loaded verbatim and injected into the system prompt at turn time.

**Future state (Phase 5+):**

```
Document
 ├── id            (stable reference ID)
 ├── path          (filesystem path or URL)
 ├── content_type  (markdown, plaintext, PDF, code, ...)
 ├── chunks        (indexed for retrieval)
 ├── embeddings    (vector representations)
 ├── metadata      (author, created_at, tags, source)
 └── relationships (links to other documents, memories, tasks)
```

Documents are ingested through the knowledge pipeline (see `KNOWLEDGE_MODEL.md`) rather than injected verbatim. The agent retrieves relevant chunks at turn time rather than receiving all documents unconditionally.

---

### Memories

Memories are agent-generated structured knowledge. Unlike documents (which are operator-provided), memories are created by the agent during its work.

```
Memory Node
 ├── id            (UUID)
 ├── agent_id      (which agent created this)
 ├── content       (natural language description)
 ├── node_type     (insight | decision | outcome | failure)
 ├── tags          (searchable labels)
 ├── extra         (execution_unit_id, source context)
 └── created_at
```

Memories are recalled semantically at turn time and injected into the system prompt. They represent what the agent has *learned* across sessions — decisions made, outcomes observed, patterns recognized.

---

### Tasks

Tasks are tracked work items. They differ from memories in that they have an explicit lifecycle (open → in progress → complete → abandoned) and can be referenced by other workspace objects.

**Current state:** Tasks are not explicitly modeled. Agents track task-like information through memories.

**Future state (Phase 5+):** Tasks are first-class workspace objects with structured status, assignee (which agent), due dates, and linked documents/memories.

---

### Assets

Assets are binary or non-textual workspace objects: images, data files, exported artifacts, generated outputs.

**Current state:** Assets are files in the workspace directory, accessible like documents.

**Future state (Phase 5+):** Assets are typed, tagged, and linked to the document and memory graph. The agent can reference an asset by ID rather than path.

---

### Agents

A workspace declares which agents operate inside it. Multiple agents can share a workspace with different roles:

```
Workspace: "project-alpha"
 ├── Agent: main        (general assistant, full workspace access)
 ├── Agent: coder       (code generation, workspace read-only)
 └── Agent: reviewer    (review and critique, no write access)
```

**Current state:** Each agent has its own isolated workspace. Workspace sharing is not yet implemented.

**Future state (Phase 5+):** Multiple agents share a workspace with per-agent permission scoping.

---

### Relationships

Relationships are typed links between workspace objects:

```
Document A --references--> Document B
Memory     --derived-from--> Document C
Task       --produces--> Asset D
Memory     --contradicts--> Memory E
```

Relationships form the **knowledge graph** within a workspace. The agent can traverse relationships to discover relevant context beyond what semantic search returns.

**Current state:** Relationships are not modeled. Agents discover connections through semantic recall.

**Future state (Phase 5+):** Relationships are explicit typed edges in the workspace graph.

---

## Workspace Lifecycle

```
Created
    ↓
Bootstrapped     ← workspace directory initialized, default docs loaded
    ↓
Active           ← agents operating inside workspace; memories accumulating
    ↓
Knowledge-indexed  ← documents ingested, chunked, embedded (Phase 5+)
    ↓
Archived / Reset   ← session reset, scheduled cleanup
```

---

## Workspace Boundaries

A workspace is a **trust boundary**. Objects inside a workspace are visible to agents operating in that workspace (subject to per-agent permissions). Objects outside a workspace are not visible.

This has implications for:

- **Data isolation:** Multiple workspaces on the same Claw instance are isolated by default
- **Agent scope:** An agent operating in workspace A cannot access documents or memories in workspace B
- **Multi-agent coordination (Phase 5+):** Cross-workspace agent communication happens through explicit handoff mechanisms, not shared memory

---

## Current Implementation vs. Future Model

| Concept | Current | Phase 5+ |
|---|---|---|
| Workspace identity | Implicit (`agent_id`) | Explicit object with ID, name, owner |
| Documents | Files in workspace dir | Indexed, chunked, embedded |
| Memories | SQLite or AINDY MAS nodes | Same, but linked to document/task graph |
| Tasks | Informal (memory nodes) | First-class objects with lifecycle |
| Assets | Files in workspace dir | Typed, tagged, linked |
| Agents per workspace | One | Many, with role-based access |
| Relationships | None | Typed edges in knowledge graph |
| Retrieval | Verbatim file injection | Semantic search + graph traversal |
