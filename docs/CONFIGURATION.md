# Configuration Reference — Infinity Claw

All Claw configuration lives in `claw.toml` at the project root (or the path passed via `--config`). Every field has a safe default; a minimal config only needs credentials and at least one agent.

---

## Top-level fields

| Key | Type | Default | Description |
|---|---|---|---|
| `state_dir` | string | `"~/.claw"` | Root directory for all runtime state (SQLite databases, PID file, node_id, agent workspaces). Tilde-expanded. |
| `log_level` | string | `"info"` | Uvicorn/Python log level: `debug`, `info`, `warning`, `error`. |

---

## `[gateway]`

HTTP server settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Bind address. Set to `"0.0.0.0"` to accept external connections. |
| `port` | integer | `18789` | TCP port. Override at runtime with `claw start --port N`. |
| `token` | string | `null` | Static bearer token for auth. `null` disables auth (open mode). Can also be set via the `CLAW_GATEWAY_TOKEN` environment variable. |

```toml
[gateway]
host  = "0.0.0.0"
port  = 18789
token = "change-me"
```

---

## `[agents.defaults]`

Default model settings applied to every agent unless overridden.

| Key | Type | Default | Description |
|---|---|---|---|
| `workspace` | string | `""` | Default workspace path. Resolved per-agent if empty. |
| `model.primary` | string | `"claude-sonnet-4-6"` | Model ID for all agents unless each agent sets its own. |
| `model.fallbacks` | list[string] | `[]` | Ordered fallback model IDs. |
| `model.max_tokens` | integer | `4096` | Max tokens per response. |
| `model.temperature` | float | `0.7` | Sampling temperature. |

```toml
[agents.defaults]
[agents.defaults.model]
primary    = "claude-sonnet-4-6"
max_tokens = 4096
temperature = 0.7
```

---

## `[[agents.list]]`

Repeatable. Each block defines one agent. The TOML key is `[[agents.list]]` (not `[[agents.agents]]`).

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | string | required | Unique agent identifier. Used as the workspace directory name and memory namespace. |
| `name` | string | `""` | Human-readable display name. Defaults to `id` if empty. |
| `workspace` | string | `""` | Explicit workspace path. If empty, defaults to `<state_dir>/agents/<id>/workspace`. |
| `agent_dir` | string | `""` | Agent state directory. If empty, defaults to `<state_dir>/agents/<id>`. |
| `default` | bool | `false` | Marks this agent as the fallback for unrouted messages. First agent is used if none is marked default. |
| `cross_agent_memory` | list[string] | `[]` | Agent IDs whose memories are also recalled at turn time (up to 3 results per source). Requires coordination or standalone memory setup. |
| `model` | table | (inherits defaults) | Per-agent model override. Same fields as `[agents.defaults.model]`. |
| `capabilities` | table | `null` | Permission restrictions for this agent. See [Capabilities](#capabilities) below. `null` means full access. |

```toml
[[agents.list]]
id      = "main"
name    = "Claw"
default = true

[agents.list.model]
primary    = "claude-sonnet-4-6"
max_tokens = 8192

[[agents.list]]
id      = "researcher"
name    = "Researcher"
cross_agent_memory = ["main"]

[agents.list.model]
primary = "claude-haiku-4-5-20251001"
```

### Capabilities

Declared as an inline table or subsection on `[[agents.list]]`. All fields are optional; omit to grant full access.

```toml
[[agents.list]]
id = "restricted"
capabilities = { tool_use = { deny = ["browser_fetch"] } }
```

Or as a subsection:

```toml
[[agents.list]]
id = "sandboxed"

[agents.list.capabilities.tool_use]
deny = ["browser_fetch", "write_file"]

[agents.list.capabilities.external_http]
enabled   = true
allowlist = ["https://api.example.com"]

[agents.list.capabilities.skill_use]
allow = ["summarize", "translate"]

[agents.list.capabilities.filesystem]
read  = true
write = false
paths = ["/home/user/docs"]
```

**`tool_use`**

| Key | Type | Default | Description |
|---|---|---|---|
| `allow` | list[string] | `["*"]` | Tool names allowed. `["*"]` means all. |
| `deny` | list[string] | `[]` | Tool names blocked even if in allow list. Deny takes precedence. |

**`skill_use`**

| Key | Type | Default | Description |
|---|---|---|---|
| `allow` | list[string] | `["*"]` | Skill names allowed. `["*"]` means all. Applied after the global skill gate. |
| `deny` | list[string] | `[]` | Skill names blocked. |

**`external_http`**

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Whether `browser_fetch` is allowed at all. |
| `allowlist` | list[string] | `[]` | URL prefixes allowed. Empty = any public URL. |
| `denylist` | list[string] | `[]` | URL substrings blocked. |

Note: RFC-1918 and loopback addresses are always blocked for `browser_fetch` regardless of this config.

**`filesystem`**

Reserved for future absolute-path tools. Workspace-scoped tools (`ws_*`) always pass through regardless of these settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `read` | bool | `false` | Allow filesystem read tools. |
| `write` | bool | `false` | Allow filesystem write tools. |
| `delete` | bool | `false` | Allow filesystem delete tools. |
| `paths` | list[string] | `[]` | Allowed path prefixes. Empty = workspace only. |

---

## `[[credentials]]`

API credentials for LLM providers. Multiple credentials are supported for key rotation and fallback.

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | string | `""` | Unique ID for this credential. Auto-assigned if empty. |
| `provider` | string | `"anthropic"` | LLM provider: `"anthropic"` or `"openai"`. |
| `api_key` | string | required | API key. Can use environment variable interpolation. |
| `model` | string | `""` | Model ID this credential is paired with. |
| `base_url` | string | `null` | Custom API base URL (for OpenAI-compatible endpoints). |
| `priority` | integer | `0` | Higher priority credentials are tried first. |
| `context_window` | integer | `200000` | Context window size in tokens. |

```toml
[[credentials]]
provider = "anthropic"
api_key  = "${ANTHROPIC_API_KEY}"
model    = "claude-sonnet-4-6"
priority = 10
```

---

## `[[bindings]]`

Route inbound messages from specific channels or peers to a specific agent.

| Key | Type | Default | Description |
|---|---|---|---|
| `agent_id` | string | required | Target agent for messages matching this binding. |
| `match.channel` | string | `null` | Channel type (e.g. `"discord"`, `"telegram"`). |
| `match.channel_id` | string | `null` | Specific channel/room ID. |
| `match.peer_id` | string | `null` | Specific user/peer ID. |
| `match.account_id` | string | `null` | Account ID (channel-specific). |
| `match.guild_id` | string | `null` | Discord guild ID. |
| `match.team_id` | string | `null` | Slack team ID. |
| `match.roles` | list[string] | `[]` | Required roles (channel-specific). |

```toml
[[bindings]]
agent_id = "researcher"
[bindings.match]
channel = "discord"
guild_id = "123456789"
```

---

## `[session]`

Conversation session behaviour.

| Key | Type | Default | Description |
|---|---|---|---|
| `dm_scope` | string | `"main"` | Session scoping mode: `"main"` (one session per agent), `"per-peer"`, `"per-channel-peer"`, `"per-account-channel-peer"`. |
| `max_messages` | integer | `200` | Message count at which the history is pruned (oldest messages removed). |
| `compaction_threshold` | integer | `40` | Message count at which the LLM is called to summarize the conversation. |
| `compaction_keep_recent` | integer | `20` | Messages kept verbatim after compaction (most recent). |
| `reset.enabled` | bool | `true` | Enable daily session reset. |
| `reset.hour` | integer | `4` | Hour of day (local time) for session reset. |
| `reset.minute` | integer | `0` | Minute for session reset. |
| `identity_links` | dict | `{}` | Link peer IDs across channels to the same identity: `{ alice = ["discord:123", "telegram:456"] }`. |

```toml
[session]
dm_scope             = "per-peer"
max_messages         = 200
compaction_threshold = 40
compaction_keep_recent = 20

[session.reset]
enabled = true
hour    = 4
minute  = 0
```

---

## `[channels]`

### `[channels.webchat]`

Built-in browser chat UI (always available).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable the WebChat UI at `GET /`. |
| `static_dir` | string | `""` | Custom static file directory. Defaults to the bundled `claw_webchat/static/`. |

### External channels

External channel adapters are configured under `[channels.extra.<name>]`. Each adapter reads its own keys from this section. See each adapter's documentation for its specific keys.

```toml
[channels.extra.telegram]
token = "${TELEGRAM_BOT_TOKEN}"

[channels.extra.discord]
token   = "${DISCORD_BOT_TOKEN}"
guild_id = "optional-guild-id"

[channels.extra.slack]
bot_token    = "${SLACK_BOT_TOKEN}"
signing_secret = "${SLACK_SIGNING_SECRET}"
```

---

## `[skills]`

File-based skills that are injected into the system prompt.

| Key | Type | Default | Description |
|---|---|---|---|
| `extra_dirs` | list[string] | `[]` | Additional directories to scan for skill files (`.md`, `.txt`). |
| `allow` | list[string] | `[]` | Skill names explicitly allowed. Empty = all skills. |
| `deny` | list[string] | `[]` | Skill names blocked globally. |

Skills are loaded from `<state_dir>/skills/` and any `extra_dirs`. Per-agent skill gates are declared in `capabilities.skill_use` on `[[agents.list]]`.

```toml
[skills]
extra_dirs = ["skills/"]
deny       = ["internal-debug"]
```

---

## `[memory]`

Persistent agent memory (recall and injection into context).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable memory tools (`remember`, `recall`, `forget`, etc.). |
| `backend` | string | `"sqlite"` | Storage backend. Currently only `"sqlite"` for local storage. |
| `db_path` | string | `""` | Path to the SQLite database. Empty = `<state_dir>/memory.db`. |

The AINDY memory backend is configured separately via `[aindy] memory_backend`.

```toml
[memory]
enabled = true
```

---

## `[knowledge]`

Workspace file indexing for retrieval-augmented context.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable knowledge indexing and retrieval. |
| `db_path` | string | `""` | Path to the FTS5 SQLite database. Empty = `<state_dir>/knowledge.db`. |
| `chunk_size` | integer | `500` | Characters per chunk when ingesting documents. |
| `chunk_overlap` | integer | `50` | Character overlap between adjacent chunks. |
| `top_k` | integer | `5` | Maximum chunks injected into the system prompt per turn. |

When enabled, Claw scans each agent's workspace directory on startup, indexes supported files (Markdown, plaintext, HTML, code, CSV), and injects relevant chunks into the system prompt. The `KnowledgeWatcher` background task auto-reindexes on file changes.

```toml
[knowledge]
enabled      = true
chunk_size   = 500
chunk_overlap = 50
top_k        = 5
```

---

## `[workspace]`

Structured workspace objects (Documents, Tasks, Assets) with per-agent permissions.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable workspace object store and tools. |
| `db_path` | string | `""` | Path to the SQLite database. Empty = `<state_dir>/workspace.db`. |

When enabled, agents get access to `ws_create_document`, `ws_list_documents`, `ws_get_document`, `ws_create_task`, `ws_list_tasks`, `ws_update_task` tools. Also enables workspace federation REST endpoints when `weave.enabled = true`.

```toml
[workspace]
enabled = true
```

---

## `[aindy]`

AINDY execution kernel integration.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable AINDY integration. Requires `api_key`. |
| `url` | string | `"http://localhost:8000"` | AINDY platform URL. |
| `api_key` | string | `""` | AINDY API key or JWT bearer token. Can be set via `AINDY_API_KEY` env var. |
| `emit_events` | bool | `true` | Fire turn lifecycle events (`turn.start`, `turn.complete`, `turn.error`, `session.started`, `memory.written`, etc.) to AINDY. Fire-and-forget; never blocks a turn. |
| `memory_backend` | string | `"local"` | Where memories are stored: `"local"` (SQLite only), `"aindy"` (AINDY MAS only, raises on failure), `"aindy-fallback"` (AINDY with automatic SQLite fallback). |
| `user_id` | string | `"claw"` | MAS identity root for memory path namespacing (`/memory/{user_id}/...`). |
| `mounted` | bool | `false` | Set to `true` when Claw is registered inside the AINDY platform layer. Bypasses auth, suppresses `/health`/`/ready`. |

```toml
[aindy]
enabled        = true
url            = "http://localhost:8000"
api_key        = "${AINDY_API_KEY}"
emit_events    = true
memory_backend = "aindy-fallback"
```

---

## `[coordination]`

Multi-agent task delegation (one agent handing off to another on the same node).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Register the `delegate_to_agent` tool. Enables agent-to-agent handoffs. |

When enabled, any agent can call `delegate_to_agent` with a target `agent_id` and `prompt`. Delegation sessions are persistent within a caller session.

```toml
[coordination]
enabled = true
```

---

## `[weave]`

Distributed multi-node peer network. Enables cross-node delegation, workspace federation, and agent discovery.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable Weave peer networking and register all `weave_*` tools. |
| `node_id` | string | `""` | Explicit node ID (UUID). If empty, a UUID is auto-generated and persisted at `<state_dir>/node_id` on first start. |
| `db_path` | string | `""` | Path to the peer registry SQLite database. Empty = `<state_dir>/weave.db`. |

Weave tools available when enabled: `weave_delegate`, `weave_list_nodes`, `weave_list_agents`, `weave_list_workspace_documents`, `weave_read_document`, `weave_list_workspace_tasks`, `weave_discover_agents`, `weave_create_document`, `weave_create_task`, `weave_update_task`, `weave_search_knowledge`.

```toml
[weave]
enabled = true
node_id = ""   # auto-generated
```

---

## `[[cron]]`

Scheduled jobs. Each block defines one cron job.

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | string | `""` | Unique job ID. Auto-assigned if empty. |
| `agent_id` | string | `"main"` | Agent that executes the prompt. |
| `prompt` | string | required | Prompt sent to the agent on schedule. |
| `cron` | string | required | 5-part cron expression (`"0 9 * * 1-5"` = 9 AM weekdays). |
| `delivery` | string | `"announce"` | How to deliver the result: `"announce"` (post to channel), `"webhook"` (POST to URL), `"none"` (run silently). |
| `delivery_channel` | string | `""` | Channel name for `announce` delivery. |
| `delivery_peer` | string | `""` | Peer ID for `announce` delivery. |
| `webhook_url` | string | `""` | URL for `webhook` delivery. |
| `enabled` | bool | `true` | Whether this job runs. Set to `false` to disable without removing. |

```toml
[[cron]]
id       = "morning-brief"
agent_id = "main"
prompt   = "Produce a brief morning status summary."
cron     = "0 9 * * 1-5"
delivery = "announce"

[[cron]]
id          = "weekly-digest"
agent_id    = "researcher"
prompt      = "Summarize this week's key findings."
cron        = "0 17 * * 5"
delivery    = "webhook"
webhook_url = "https://hooks.example.com/claw-digest"
```

---

## Environment variables

These override the corresponding `claw.toml` fields at runtime:

| Variable | Overrides |
|---|---|
| `ANTHROPIC_API_KEY` | Used automatically by `[[credentials]]` with `provider = "anthropic"` |
| `CLAW_GATEWAY_TOKEN` | `gateway.token` |
| `AINDY_API_KEY` | `aindy.api_key` |
| `AINDY_URL` | `aindy.url` |
| `CLAW_ENV` | Passed to observability framework as the deployment environment label |

---

## Minimal working config

```toml
# claw.toml

[gateway]
host  = "127.0.0.1"
port  = 18789

[[credentials]]
provider = "anthropic"
api_key  = "${ANTHROPIC_API_KEY}"
model    = "claude-sonnet-4-6"

[[agents.list]]
id      = "main"
name    = "Claw"
default = true
```
