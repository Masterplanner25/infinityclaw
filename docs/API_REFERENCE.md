# API Reference — Infinity Claw Gateway

The Claw gateway exposes HTTP REST endpoints and WebSocket connections. All endpoints are served from the same host and port (default `http://127.0.0.1:18789`).

---

## Authentication

When `gateway.token` is set (or `CLAW_GATEWAY_TOKEN` env var), all connections require a credential. Three methods are accepted:

| Method | How to supply |
|---|---|
| Static bearer token | `Authorization: Bearer <token>` |
| JWT (issued by `/auth/token`) | `Authorization: Bearer <jwt>` |
| API key (issued by `/auth/keys`) | `Authorization: Bearer <key>` or `X-API-Key: <key>` |
| WebSocket token | `?token=<value>` query parameter, or `Authorization`/`X-API-Key` header on the upgrade request |

When auth is not configured (`gateway.token` not set and no AuthManager), all connections are accepted without a credential.

In AINDY mounted mode (`aindy.mounted = true`), auth is bypassed entirely — the AINDY platform layer handles it upstream.

---

## Standalone-only endpoints

These endpoints are only registered when `aindy.mounted = false` (the default).

### `GET /health`

Liveness probe.

**Response**
```json
{ "status": "ok", "service": "claw-gateway" }
```

---

### `GET /ready`

Readiness probe.

**Response**
```json
{ "status": "ready" }
```

---

## Core endpoints

### `GET /`

Serves the built-in WebChat UI (`index.html`). Requires `channels.webchat.enabled = true` (default).

---

### `WS /ws/chat`

WebChat WebSocket connection. Accepts text messages and streams assistant responses back.

**Auth:** Token via `?token=` query param or `Authorization` / `X-API-Key` / `X-Claw-Token` header on upgrade.

**Message format (client → server)**
```json
{ "text": "Hello, Claw!" }
```

**Message format (server → client)**

Streaming chunks are sent as they arrive from the LLM. Final message includes a `done` flag:
```json
{ "text": "chunk of response" }
{ "text": " more text", "done": true }
```

Session scoping follows `session.dm_scope` in config. Agent routing follows `[[bindings]]`.

---

### `WS /ws`

Control-plane WebSocket (stub). Accepts upgrade, sends a `hello` message, then idles.

**Response on connect**
```json
{ "type": "hello", "version": "1.0", "note": "control-plane WS -- stub" }
```

---

## Auth management

### `POST /auth/token`

Issue a short-lived JWT for a given user. Requires auth to be enabled (`gateway.token` set).

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `user_id` | string | Identity to encode in the JWT |
| `secret` | string | Must match `gateway.token` |

**Response**
```json
{ "token": "<jwt>", "type": "bearer" }
```

---

### `POST /auth/keys`

Create a persistent API key.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `label` | string | required | Human-readable label for this key |
| `scopes` | string | `"*"` | Comma-separated scopes (e.g. `"read,write"`) |

**Response**
```json
{
  "key": "ck_live_...",
  "key_id": "uuid",
  "label": "my-key",
  "scopes": ["*"]
}
```

The raw key is only returned at creation time. Store it securely.

---

### `GET /auth/keys`

List all API keys (metadata only; raw keys are never returned after creation).

**Response**
```json
{
  "keys": [
    {
      "key_id": "uuid",
      "label": "my-key",
      "scopes": ["*"],
      "created_at": "2026-06-20T12:00:00",
      "last_used": "2026-06-20T14:30:00"
    }
  ]
}
```

---

### `DELETE /auth/keys/{key_id}`

Revoke an API key immediately.

**Response**
```json
{ "revoked": true, "key_id": "uuid" }
```

**Error (404)**
```json
{ "detail": "Key not found" }
```

---

## Pairing

Used by external channel adapters to link channel peers to a known identity.

### `POST /pair/generate`

Generate a single-use pairing code.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `channel_id` | string | Channel identifier |
| `peer_id` | string | Peer/user identifier |

**Response**
```json
{ "code": "ABC123", "ttl_seconds": 300 }
```

---

### `POST /pair/approve`

Consume a pairing code and establish the identity link.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `code` | string | Code returned by `/pair/generate` |

**Response**
```json
{ "approved": true, "channel_id": "...", "peer_id": "..." }
```

**Error (400)**
```json
{ "detail": "Invalid or expired pairing code" }
```

---

## Weave endpoints

Registered only when `weave.enabled = true` in `claw.toml`.

### `GET /weave/agents`

Returns this node's ID and the list of agents running on it. Used by peer nodes during `claw weave connect` to discover the remote node ID.

**Response**
```json
{
  "node_id": "550e8400-e29b-41d4-a716-446655440000",
  "agents": [
    { "agent_id": "main", "name": "Claw" },
    { "agent_id": "researcher", "name": "Researcher" }
  ]
}
```

---

### `GET /weave/nodes`

Returns the list of registered peer nodes.

**Response**
```json
{
  "nodes": [
    { "node_id": "uuid", "url": "http://node-b:18789", "label": "Node B" }
  ]
}
```

---

### `POST /weave/nodes/register`

Register a peer node. Called automatically by `claw weave connect` on the remote node.

**Request body**
```json
{
  "node_id": "uuid",
  "url": "http://node-a:18789",
  "label": "Node A",
  "api_key": ""
}
```

**Response**
```json
{ "registered": true, "node_id": "uuid" }
```

---

### `POST /weave/delegate`

Run a prompt against a local agent. Called by remote nodes via `WeaveClient.delegate()`.

**Request body**
```json
{
  "from_node": "source-node-uuid",
  "agent_id": "main",
  "prompt": "What is the status of project X?",
  "context": "",
  "session_key": "weave:node-a:session-123:node-b:main"
}
```

`session_key` is optional. When provided, the delegation session accumulates history across calls.

**Response**
```json
{ "response": "Project X is...", "agent_id": "main" }
```

---

## Workspace federation endpoints

Registered only when **both** `weave.enabled = true` AND `workspace.enabled = true`.

All endpoints use `{agent_id}` to scope to that agent's home workspace.

### `GET /weave/workspace/{agent_id}/documents`

List documents in an agent's workspace.

**Response**
```json
{
  "agent_id": "researcher",
  "documents": [
    {
      "id": "uuid",
      "workspace_id": "researcher",
      "name": "plan.md",
      "body": "...",
      "content_type": "text",
      "created_at": "2026-06-20T12:00:00",
      "updated_at": "2026-06-20T12:00:00"
    }
  ]
}
```

---

### `GET /weave/workspace/{agent_id}/documents/{doc_id}`

Fetch a single document by ID.

Returns **404** if the document does not exist or belongs to a different agent (prevents cross-workspace leakage via guessed IDs).

**Response:** Document object (same shape as the list entry above).

---

### `POST /weave/workspace/{agent_id}/documents`

Create or upsert a document in an agent's workspace. Upsert matches on `(workspace_id, name)` — same name replaces body.

**Request body**
```json
{
  "name": "plan.md",
  "body": "# Project Plan\n...",
  "content_type": "text"
}
```

**Response:** Created/updated document object.

---

### `GET /weave/workspace/{agent_id}/tasks`

List tasks in an agent's workspace.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `status` | string | Optional filter: `open`, `in_progress`, `done`, `cancelled` |

**Response**
```json
{
  "agent_id": "researcher",
  "tasks": [
    {
      "id": "uuid",
      "workspace_id": "researcher",
      "title": "Draft report",
      "body": "",
      "status": "open",
      "priority": 0,
      "created_at": "2026-06-20T12:00:00",
      "updated_at": "2026-06-20T12:00:00"
    }
  ]
}
```

---

### `POST /weave/workspace/{agent_id}/tasks`

Create a task in an agent's workspace.

**Request body**
```json
{
  "title": "Draft report",
  "body": "Include Q2 metrics",
  "priority": 1
}
```

**Response:** Created task object.

---

### `PATCH /weave/workspace/{agent_id}/tasks/{task_id}`

Update a task. Only fields present in the body are changed.

Returns **404** if the task does not exist or belongs to a different agent.

**Request body** (all fields optional)
```json
{
  "status": "in_progress",
  "title": "Draft Q2 report",
  "body": "Updated description",
  "priority": 2
}
```

Valid `status` values: `open`, `in_progress`, `done`, `cancelled`.

**Response:** Updated task object.

---

## Knowledge federation endpoint

Registered only when **both** `weave.enabled = true` AND `knowledge.enabled = true`.

### `GET /weave/workspace/{agent_id}/knowledge`

Search an agent's FTS5 knowledge index.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | required | Search query |
| `limit` | integer | `5` | Maximum number of chunks to return |

**Response**
```json
{
  "agent_id": "researcher",
  "chunks": [
    {
      "chunk_id": "uuid",
      "workspace_id": "researcher",
      "source_path": "/path/to/file.md",
      "text": "Relevant chunk content...",
      "chunk_index": 0
    }
  ]
}
```

Chunks are ranked by BM25 relevance (most relevant first).
