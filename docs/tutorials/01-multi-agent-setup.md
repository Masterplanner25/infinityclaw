# Tutorial: Multi-Agent Setup

This tutorial sets up two agents — a general assistant and a specialized researcher — wired so the assistant can delegate tasks to the researcher automatically.

**What you'll build:**
- `main` — general-purpose assistant, the default for all conversations
- `researcher` — focused on research and synthesis; invoked by `main` via the `delegate_to_agent` tool

**Prerequisites:** Claw installed and running (`claw start` succeeds).

---

## Step 1 — Add the second agent

In `claw.toml`, add a second `[[agents.list]]` block:

```toml
[[agents.list]]
id      = "main"
name    = "Claw"
default = true

[agents.list.model]
primary    = "claude-sonnet-4-6"
max_tokens = 8192

[[agents.list]]
id   = "researcher"
name = "Researcher"

[agents.list.model]
primary    = "claude-sonnet-4-6"
max_tokens = 4096
```

---

## Step 2 — Enable coordination

```toml
[coordination]
enabled = true
```

This registers the `delegate_to_agent` tool on all agents. When `main` calls it, the request is dispatched to `researcher` as a full inner turn.

---

## Step 3 — Give each agent a workspace file

Agents pick up files from their workspace directory as part of their system prompt.

```powershell
# Tell main what its role is
New-Item -ItemType Directory -Force ~/.claw/agents/main/workspace
Set-Content ~/.claw/agents/main/workspace/identity.md @"
You are Claw, a general-purpose AI assistant.
You have access to a Researcher agent. For tasks requiring deep research or
synthesis, delegate to it using the delegate_to_agent tool.
"@

# Give researcher a focused identity
New-Item -ItemType Directory -Force ~/.claw/agents/researcher/workspace
Set-Content ~/.claw/agents/researcher/workspace/identity.md @"
You are the Researcher agent. You receive focused research tasks from the main assistant.
Produce thorough, well-cited answers. Focus on accuracy over brevity.
"@
```

---

## Step 4 — Restart and verify

```powershell
claw start
```

In WebChat, send `main` a message that requires research:

> "Research the current state of FTS5 in SQLite — what are its known limitations?"

`main` should delegate to `researcher`, which will produce a thorough answer, and then `main` will relay it back.

---

## Step 5 — Give researcher access to main's memories (optional)

If you want `researcher` to be aware of things `main` has learned:

```toml
[[agents.list]]
id                 = "researcher"
cross_agent_memory = ["main"]
```

`researcher` will now recall up to 3 of `main`'s memories on each turn, giving it context from the broader conversation history.

---

## Step 6 — Restrict researcher's tool access (optional)

Researcher probably doesn't need memory tools or the ability to delegate further. Lock it down:

```toml
[[agents.list]]
id = "researcher"

[agents.list.capabilities.tool_use]
deny = ["remember", "forget", "delegate_to_agent"]

[agents.list.capabilities.external_http]
enabled   = true
allowlist = ["https://en.wikipedia.org", "https://arxiv.org"]
```

Denied tools are stripped from the tool list before the LLM turn — the model never sees them and cannot attempt to call them.

---

## How delegation works

When `main` calls `delegate_to_agent`:

```
main receives user message
  └─ calls delegate_to_agent(agent_id="researcher", prompt="...")
       └─ inner turn runs on researcher
            └─ researcher produces a response
       └─ response returned to main as tool result
  └─ main incorporates result into its reply
```

The delegation session is persistent within the caller's session. If the user has an ongoing conversation with `main`, all delegations to `researcher` share a `delegate:main:<session>:researcher` session key — `researcher` accumulates history across multiple handoffs in the same conversation.

---

## Routing specific channels to specific agents

Use `[[bindings]]` to send particular users directly to `researcher`:

```toml
[[bindings]]
agent_id = "researcher"
[bindings.match]
channel = "telegram"
peer_id  = "123456789"   # your Telegram user ID
```

That peer always talks to `researcher` directly, bypassing `main`.
