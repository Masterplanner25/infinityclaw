# Agent Specification — Infinity Claw

## What Is an Agent?

An agent in Infinity Claw is a persistent, context-aware entity that operates inside a workspace. It is not a stateless function call. It is not a chat session. It is a named identity with its own memory, workspace, tool surface, and capability profile — reachable across channels and persistent across restarts.

An agent is defined by its **contract**: what it knows, what it can do, and what it is not allowed to do.

---

## Agent Identity

```toml
[[agents.list]]
id      = "main"        # unique within the gateway; used in routing and memory namespacing
name    = "Claw"        # display name; injected into system prompt
default = true          # receives messages when no binding matches
```

Every agent has:

- A stable `id` — used as the namespace key for memory, workspace, and routing
- A display `name` — visible to users, injected into the system prompt
- A `default` flag — at most one agent is the fallback for unbound messages

---

## Agent Memory

Each agent has an isolated memory namespace. The LLM interacts with memory through tools; it never sets `agent_id` directly.

```
Memory namespace:  /memory/{user_id}/claw/{agent_id}/{node_type}/{node_id}
```

**Node types:** `insight`, `decision`, `outcome`, `failure`

Memory operations available to the agent:
- `remember(content)` — store a new memory node
- `recall(query)` — semantic search over this agent's memories
- `list_memories()` — enumerate all stored nodes
- `forget(node_id)` — delete a specific node

Memory is injected into the system prompt at the start of every turn (top-N recalled nodes). The agent sees relevant context automatically; it does not need to query memory to be aware of past interactions.

---

## Agent Workspace

Each agent has a dedicated workspace directory:

```
~/.claw/agents/{agent_id}/workspace/
```

The workspace is a filesystem-backed container for files the agent can read and write. At turn start, workspace files are loaded and injected into the system prompt alongside memories.

**Current capability:**
- Read access to workspace files (injected at turn time)
- Write access via workspace tools (file write, append)

**Future (Phase 5+):**
- Workspace becomes a first-class structured object (see `WORKSPACE_SPEC.md`)
- Files are indexed through the knowledge layer rather than injected verbatim
- Relationships between documents are tracked

---

## Agent Tools

Tools are registered on the shared `ToolRegistry`. Each agent sees the same tool definitions, but the `scoped_executor` injects `agent_id` at invocation time — so tool handlers always know which agent is acting.

**Built-in tools:**

| Tool | Description |
|---|---|
| `remember` | Store a memory node |
| `recall` | Semantic search over agent memories |
| `list_memories` | List all memory nodes for this agent |
| `forget` | Delete a memory node |
| `browser_fetch` | Fetch a URL and return content |

**Skills** extend the tool surface. Skills are `.skill` files discovered at startup and gated per-agent through the allow/deny list.

---

## Agent Model Configuration

Each agent can specify its own model configuration. If not set, the gateway-level default applies.

```toml
[[agents.list]]
id = "coder"
name = "Claw Coder"

[agents.list.model]
primary    = "claude-haiku-4-5-20251001"
max_tokens = 2048
temperature = 0.5
fallbacks   = []
```

The credential store supports multiple profiles with priority-based rotation. Key failures automatically fall back to the next available profile.

---

## Agent Capabilities

A capability is a category of action the agent is permitted to take. Capabilities are declared in the agent config and enforced at the tool and skill layers.

**Current capabilities (implicit — all agents):**
- Memory read/write
- Workspace file read
- HTTP fetch (browser_fetch tool)
- Skill invocation (filtered by allow/deny)

**Planned capability model:**

```toml
[[agents.list]]
id = "main"

[agents.list.capabilities]
memory        = { read = true, write = true }
workspace     = { read = true, write = true }
filesystem    = { read = false, write = false }   # explicit deny; see PERMISSIONS_AND_SECURITY.md
external_http = { enabled = true }
tool_use      = { allowed = ["remember", "recall", "browser_fetch"] }
```

---

## Agent Lifecycle

```
configured
    ↓
initialized      ← AgentRegistry.__init__() builds ConversationalTurn
    ↓
idle             ← waiting for inbound message
    ↓
running          ← inside _run_turn(); session lock held
    ↓
compacting       ← ClawSessionManager.compact_if_needed() (threshold: 40 messages)
    ↓
idle             ← turn complete; lock released
```

**Session state per agent:**

- Message history (compacted at threshold, pruned at max)
- Active `asyncio.Lock` per session key (concurrent sessions across different keys are independent)
- AINDY `execution_unit_id` per turn (UUID, threaded through memory writes and events)

Agents do not persist in memory between turns. The `ConversationalTurn` is stateless at runtime; state lives in the session manager and memory store.

---

## Agent Isolation Guarantees

- Memory is namespaced per `agent_id` — agents cannot read each other's memories
- Workspace directories are per-agent — no shared file access (today)
- Tool invocations carry `agent_id` in the scoped executor — a tool called by `main` cannot affect `coder`'s memory
- Session locks are per `(agent_id, channel_id, peer_id)` — concurrent messages to different agents do not block

---

## Future: Agent Permissions (Phase 5+)

See `PERMISSIONS_AND_SECURITY.md` for the full permissions model. In brief:

- Per-agent capability declarations replace implicit "all tools allowed"
- Filesystem access requires explicit grant with read/write/delete scopes
- External API access requires explicit allowlist
- Skill execution gated by per-agent allow/deny (already implemented; will be extended to capability grants)
