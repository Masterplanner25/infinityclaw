# Tutorial: Connecting Weave Nodes

This tutorial sets up a two-node Weave network where agents on separate machines can delegate tasks to each other, read each other's workspace documents, and search each other's knowledge indexes.

**What you'll build:**
- Node A: a Claw instance with a `researcher` agent
- Node B: a Claw instance with a `writer` agent
- Node A's writer delegates research tasks to Node B's researcher via Weave

**Prerequisites:** Claw running and accessible on two machines (or two ports on the same machine for local testing).

---

## Step 1 — Enable Weave on both nodes

**Node A (`claw.toml`):**

```toml
[gateway]
host  = "0.0.0.0"
port  = 18789
token = "node-a-secret"

[weave]
enabled = true
# node_id is auto-generated on first start and persisted to ~/.claw/node_id
# Set explicitly only if you need a stable, human-readable ID:
# node_id = "node-a"
```

**Node B (`claw.toml`):**

```toml
[gateway]
host  = "0.0.0.0"
port  = 18789
token = "node-b-secret"

[weave]
enabled = true
```

Start both nodes:

```powershell
# On each machine:
claw start
```

---

## Step 2 — Connect the nodes

Connection is asymmetric — you register a peer on the node that initiates contact. For a bidirectional network, connect from both sides.

**On Node A** (registers Node B as a peer):

```powershell
claw weave connect http://node-b.example.com:18789 --label "Node B" --key "node-b-secret"
```

`connect` fetches Node B's `node_id` from `GET /weave/agents`, then saves the peer entry locally. The `--key` flag supplies the auth token for the remote (omit if Node B has no token set).

**On Node B** (registers Node A as a peer):

```powershell
claw weave connect http://node-a.example.com:18789 --label "Node A" --key "node-a-secret"
```

Verify both sides:

```powershell
claw weave status   # shows: local node_id = <uuid>, peers: 1
claw weave nodes    # lists the registered peer
```

---

## Step 3 — List agents across the Weave

Once nodes are connected, you can discover what agents are available on each peer:

```powershell
# From Node A, via the CLI (WebChat also works — ask the agent)
# Or via the API:
curl -H "Authorization: Bearer node-a-secret" http://node-a.example.com:18789/weave/agents
```

The `weave_discover_agents` tool performs the same query across all registered nodes simultaneously:

> "What agents are available across the Weave?"

The agent calls `weave_discover_agents`, which does a concurrent `asyncio.gather` across all registered nodes and returns a flat list of `{agent_id, name, node_id, node_url}` entries.

---

## Step 4 — Delegate across nodes

With Weave enabled, the `weave_delegate` tool lets agents on Node A run tasks on agents on Node B.

Example: Node A's `writer` agent asks Node B's `researcher` agent to research a topic.

The LLM on Node A calls:

```json
{
  "tool": "weave_delegate",
  "input": {
    "node_url": "http://node-b.example.com:18789",
    "agent_id": "researcher",
    "prompt": "What are the current limitations of SQLite FTS5?"
  }
}
```

Node A sends this to `POST /weave/delegate` on Node B, which runs a full inner turn on the `researcher` agent and returns the response.

**Session persistence:** Cross-node delegation uses a session key `weave:{from_node}:{caller_session}:{to_node}:{agent_id}` — the remote agent accumulates history across multiple delegations in the same caller session.

---

## Step 5 — Access workspace documents across nodes

With both `weave.enabled = true` and `workspace.enabled = true` on Node B, Node A can read Node B's workspace documents.

**On Node B** (`claw.toml`):

```toml
[workspace]
enabled = true
```

List documents on the remote node:

> "List the documents in the researcher agent's workspace on Node B"

The agent calls `weave_list_workspace_documents`:

```json
{
  "tool": "weave_list_workspace_documents",
  "input": {
    "node_url": "http://node-b.example.com:18789",
    "agent_id": "researcher"
  }
}
```

Read a specific document:

```json
{
  "tool": "weave_read_document",
  "input": {
    "node_url": "http://node-b.example.com:18789",
    "agent_id": "researcher",
    "document_id": "doc-uuid-here"
  }
}
```

Create a document on the remote node:

```json
{
  "tool": "weave_create_document",
  "input": {
    "node_url": "http://node-b.example.com:18789",
    "agent_id": "researcher",
    "name": "research-notes.md",
    "body": "# Research Notes\n\nFindings from the FTS5 investigation..."
  }
}
```

---

## Step 6 — Search knowledge across nodes

With both `weave.enabled = true` and `knowledge.enabled = true` on Node B:

> "Search Node B's knowledge base for 'FTS5 limitations'"

The agent calls `weave_search_knowledge`:

```json
{
  "tool": "weave_search_knowledge",
  "input": {
    "node_url": "http://node-b.example.com:18789",
    "agent_id": "researcher",
    "query": "FTS5 limitations",
    "limit": 5
  }
}
```

This calls `GET /weave/workspace/researcher/knowledge?q=FTS5+limitations&limit=5` on Node B and returns the top-matching chunks from Node B's FTS5 index.

---

## Local two-node test setup

To test the full Weave setup on a single machine, run two instances on different ports:

**Node A** (`claw-a.toml`):

```toml
[gateway]
port = 18789

[weave]
enabled = true
node_id = "node-a"

[aindy]
# Use a separate state dir so the databases don't collide
state_dir = "~/.claw-a"
```

**Node B** (`claw-b.toml`):

```toml
[gateway]
port = 18790

[weave]
enabled = true
node_id = "node-b"

[aindy]
state_dir = "~/.claw-b"
```

Start both:

```powershell
Start-Process -NoNewWindow venv\Scripts\python.exe "-m claw start --config claw-a.toml"
Start-Process -NoNewWindow venv\Scripts\python.exe "-m claw start --config claw-b.toml"
```

Connect:

```powershell
# From Node A config context:
venv\Scripts\python.exe -m claw --config claw-a.toml weave connect http://127.0.0.1:18790
venv\Scripts\python.exe -m claw --config claw-b.toml weave connect http://127.0.0.1:18789
```

---

## How the Weave REST layer works

All cross-node communication goes through these REST endpoints on the receiving node:

| Endpoint | Purpose |
|---|---|
| `GET /weave/agents` | List this node's agents + node_id (used by `connect`) |
| `GET /weave/nodes` | List this node's registered peers |
| `POST /weave/nodes/register` | Register an inbound peer |
| `POST /weave/delegate` | Run a full agent turn and return the response |
| `GET /weave/workspace/{agent_id}/documents` | List workspace documents |
| `GET /weave/workspace/{agent_id}/documents/{doc_id}` | Read a single document |
| `POST /weave/workspace/{agent_id}/documents` | Create a document |
| `GET /weave/workspace/{agent_id}/tasks` | List tasks |
| `POST /weave/workspace/{agent_id}/tasks` | Create a task |
| `PATCH /weave/workspace/{agent_id}/tasks/{task_id}` | Update a task |
| `GET /weave/workspace/{agent_id}/knowledge` | Search the knowledge index |

All endpoints require the same auth token as the main gateway (`Authorization: Bearer <token>`). The Weave endpoints are only registered when `weave.enabled = true`.
