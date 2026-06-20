# Runtime Contract — Infinity Claw

## Purpose

This document defines the technical contracts that govern how Infinity Claw executes. It is the source of truth for execution order, event sequencing, error handling, and the guarantees the runtime makes to agents, tools, and external systems.

---

## Turn Execution Contract

A **turn** is the atomic unit of agent execution: one user message in, one assistant response out (plus any intermediate tool calls). Every guarantee the runtime makes applies at the turn level.

### Turn Lifecycle

```
User Message Arrives
        ↓
1.  session_lock.acquire(session_key)
        ↓
2.  execution_unit_id = uuid4()
        ↓
3.  Load workspace files
4.  Load skills
5.  MemoryManager.recall(query) → inject top-N memories
        ↓
6.  Build system prompt (PromptContext)
7.  Append user message to history
8.  Compact if len(messages) >= threshold (LLM summarization)
9.  Prune if len(messages) > max_messages
        ↓
10. [if first message in session] fire claw.session.started (async, fire-and-forget)
        ↓
11. fire sys.v1.claw.turn.start via AINDY (async, fire-and-forget)
        ↓
12. turn.run(messages, tools, system_prompt)
          ↓
        [LLM streaming loop]
          ↓
        [tool call] → scoped_executor.invoke(tool_name, input, agent_id=agent_id, execution_unit_id=eid)
          ↓
        [continue streaming after tool response]
          ↓
        [response complete]
        ↓
13. Append assistant message to history
14. Deliver response to channel adapter
        ↓
15. fire sys.v1.claw.turn.complete via AINDY (async, fire-and-forget)
        ↓
16. session_lock.release()
```

### Turn Guarantees

- **Serialization:** Messages to the same `session_key` are serialized. Concurrent messages to different session keys execute concurrently.
- **Atomicity:** The session lock is held for the entire turn. No other turn for the same session can begin until this one completes.
- **Fire-and-forget safety:** AINDY events are always `asyncio.create_task()`. An AINDY failure never raises an exception visible to the turn pipeline.
- **Tool isolation:** Tool calls carry `agent_id` injected by `scoped_executor`. The LLM cannot pass `agent_id` as a parameter; it is always set by the runtime.
- **execution_unit_id threading:** The same `execution_unit_id` appears in AINDY events, memory node extras, and tool invocation context — forming a complete audit trail for every turn.

---

## Session Contract

A **session** is the stateful conversation history for a `(agent_id, channel_id, peer_id)` triple.

### Session Key

```python
session_key = "{channel_id}:{agent_id}:{peer_id}"
# e.g. "telegram:main:1234567"
#      "webchat:coder:anonymous"
```

`dm_scope` in config controls how much of the key is used:

| dm_scope | Key format |
|---|---|
| `main` | `":main:"` — all users share one session |
| `per-peer` | `":{peer_id}"` — one session per user |
| `per-channel-peer` | `"{channel}::{peer_id}"` — one session per user per channel |
| `per-account-channel-peer` | Full key |

### Session Lifecycle

```
first message → session created (empty history)
    ↓
subsequent messages → history grows
    ↓
len(history) >= compaction_threshold (default 40)
    → LLM summarization of older messages
    → keep last compaction_keep_recent (default 20) messages
    ↓
len(history) > max_messages (default 200)
    → hard prune: drop oldest messages
    ↓
session_reset (scheduled or manual)
    → history cleared; memories persist
```

### Session Guarantees

- Sessions are serialized per key; they are not serialized across keys
- Compaction is LLM-assisted: the LLM writes a summary that replaces the compacted messages
- Message pruning is hard (FIFO drop) and happens after compaction
- Sessions are in-memory; a Claw restart clears in-progress sessions (history lives in the session manager, not the database — persistence is a future capability)

---

## Memory Contract

### Write Path

```
agent calls remember(content, execution_unit_id=eid)
    ↓
MemoryManager._aindy_or_local(
    aindy_coro=AINDYMemoryStore.write(node),
    local_fn=lambda: local_store.save(node)
)
    ↓
[AINDY path] memory_write(MAS path, JSON payload, tags)
             → fire claw.memory.written event (fire-and-forget)
[Local path] MemorySqliteStore.save(node)
    ↓
returns MemoryNode with stable id
```

### Read Path

```
MemoryManager.recall(agent_id, query)
    ↓
[AINDY path] AINDYMemoryStore.search(query, agent_id)
[Local path] MemorySqliteStore.search(query)
    ↓
returns list[MemoryNode] (top-N by relevance)
    ↓
injected into system prompt as structured context block
```

### Memory Guarantees

- Memory is per-agent namespaced. No cross-agent reads or writes without explicit config
- `aindy-fallback` mode: if AINDY raises any exception, the local SQLite store is used transparently
- `aindy` (strict) mode: AINDY failures propagate as errors (useful for debugging)
- `local` mode: AINDY is bypassed entirely; useful for testing and air-gapped deployments
- The LLM never sees `agent_id` in the tool interface; it is injected by `scoped_executor`
- `execution_unit_id` is passed through from turn context to memory node extra; memory writes are traceable to the turn that created them

---

## Tool Contract

### Tool Registration

```python
registry.register(ToolDefinition(
    name="remember",
    description="...",
    input_schema={...},
    handler=_make_remember_handler(memory_manager),
))
```

Tools are registered once at gateway startup. Duplicate registrations are silently skipped.

### Tool Invocation

```python
result_json = await scoped_executor.invoke(
    tool_name,
    input_dict,
    agent_id=agent_id,            # injected; not from LLM
    execution_unit_id=eid,        # injected; not from LLM
)
```

The `scoped_executor` is constructed per-turn in `_run_turn`. It wraps the `ToolRegistry.invoke()` call with automatic `agent_id` and `execution_unit_id` injection.

### Tool Guarantees

- A tool not in the agent's allow list is not presented to the LLM (future: capability gating; today: allow/deny on skills, not base tools)
- Tool handlers receive `agent_id` and `execution_unit_id` from the runtime, never from LLM input
- Tool failures are returned as structured error JSON; they do not raise exceptions that abort the turn
- Tool results are appended to the message history and the LLM continues streaming

---

## Cron Contract

### Cron Job Execution

```
APScheduler fires job
    ↓
execution_unit_id = uuid4()
    ↓
fire sys.v1.job.submit via AINDY (fire-and-forget)
    ↓
ConversationalTurn.run(prompt=job.prompt, ...)
    ↓
response delivered per job.delivery:
    "announce" → channel adapter
    "webhook"  → HTTP POST to webhook_url
    "none"     → response discarded
    ↓
fire claw.cron.executed via AINDY (fire-and-forget)
```

### Cron Guarantees

- Cron jobs use the same `ConversationalTurn` as regular turns — same tool access, same memory, same prompt pipeline
- Each cron execution has its own `execution_unit_id` traceable through AINDY events
- AINDY unavailability never blocks cron job execution
- Cron jobs are not serialized against chat turns for the same agent. If a cron job fires while a chat turn is running, they execute concurrently (different session keys: cron uses `"cron:{agent_id}:{job_id}"`)

---

## AINDY Event Contract

AINDY events are fire-and-forget. The runtime emits them but does not wait for confirmation and does not retry on failure.

### Events Emitted

| Event | Trigger | Payload |
|---|---|---|
| `sys.v1.claw.turn.start` | Start of every turn | `agent_id`, `session_key`, `channel`, `execution_unit_id` |
| `sys.v1.claw.turn.complete` | Successful turn completion | `agent_id`, `session_key`, `execution_unit_id`, `response_len` |
| `sys.v1.claw.turn.error` | Turn failure | `agent_id`, `session_key`, `execution_unit_id`, `error` |
| `claw.session.started` | First message in a session | `agent_id`, `session_key`, `channel`, `execution_unit_id` |
| `claw.session.ended` | WebSocket disconnect | `agent_id`, `session_key`, `duration_ms`, `channel` |
| `claw.memory.written` | Memory node saved to AINDY MAS | `agent_id`, `node_id`, `path`, `execution_unit_id` |
| `claw.cron.executed` | Cron job turn complete | `job_id`, `agent_id`, `delivery`, `execution_unit_id`, `response_len` |

### AINDY Failure Handling

Three concentric guards prevent AINDY failures from blocking execution:

1. `self._aindy is None` — client not constructed (AINDY disabled or no api_key)
2. `if self._aindy and config.aindy.emit_events:` — gated at each call site
3. `except Exception: pass` inside `_emit_aindy()` / `_fire_event()` helpers

**Contract:** AINDY being unavailable is a non-event from the agent's perspective. Turns complete, memory is written to the local fallback, and the user receives a response.

---

## Error Handling Contract

| Error type | Behavior |
|---|---|
| LLM API error | Turn fails; `turn.error` AINDY event fired; error returned to channel |
| Tool call error | Tool returns structured error JSON; LLM sees error in tool result; turn continues |
| Memory write failure (AINDY mode) | Fallback to local SQLite (aindy-fallback); raise (aindy strict); skip (local) |
| AINDY event failure | Logged at DEBUG; execution continues |
| Session lock timeout | Not implemented; session locks are unbounded (future: configurable timeout) |
| Compaction failure | Session compaction skipped; history grows unchecked; logged as warning |

---

## Nodus Workflow Contract

Nodus workflows (`.nd` files in `workflows/`) are executed by the Nodus Language runtime. They are not part of the turn pipeline — they run alongside it at gateway lifecycle events.

| Workflow | Trigger |
|---|---|
| `boot.nd` | Gateway startup |
| `bootstrap.nd` | First-run workspace initialization |
| `heartbeat.nd` | Periodic health probe (cron-driven) |
| `session_reset.nd` | Scheduled session cleanup |

Workflow failures do not abort gateway startup. They are logged and skipped.
