# Channels — Infinity Claw

Claw supports multiple simultaneous channels. Each channel is a separate adapter package. All channels share the same agent registry and memory — a user talking via Telegram and WebChat with the same agent identity gets a unified conversation.

---

## WebChat (built-in)

The browser-based chat UI. Always available. No external accounts or tokens needed.

**Config** (`claw.toml`)

```toml
[channels.webchat]
enabled    = true    # default: true
static_dir = ""      # defaults to bundled claw_webchat/static/
```

**Access:** `http://host:port/` — opens the chat UI in any browser.

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | Yes |
| Attachments | No |
| Threads | No |
| Max message length | 10,000 chars |

**WebSocket protocol** (for custom clients)

Connect to `ws://host:port/ws/chat`. On connect, the server sends:

```json
{ "type": "hello", "peer_id": "uuid", "channel": "webchat" }
```

Send a message:

```json
{ "type": "chat", "content": "Hello" }
```

Response arrives as streaming chunks:

```json
{ "type": "chunk", "content": "partial response..." }
{ "type": "done" }
```

Other frame types: `ping` → `pong`, `error`.

---

## Discord

Adapter: `claw_discord` (discord.py 2.x)

**Setup**

1. Create a bot at [discord.com/developers](https://discord.com/developers)
2. Enable **Message Content Intent** and **DM Messages intent** in the Bot settings
3. Invite the bot to your server with `bot` scope and `Send Messages` + `Read Message History` permissions
4. Copy the bot token

**Config**

```toml
[channels.extra.discord]
token           = "${DISCORD_BOT_TOKEN}"
require_mention = true    # default: true
allowed_guilds  = []      # empty = all guilds; e.g. [123456789, 987654321]
```

| Key | Type | Default | Description |
|---|---|---|---|
| `token` | string | required | Bot token from Discord developer portal |
| `require_mention` | bool | `true` | In guild channels, the bot must be `@mentioned` to respond. DMs and threads always respond. |
| `allowed_guilds` | list[int] | `[]` | Restrict to specific guild IDs. Empty = accept all guilds. |

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | Yes (Discord subset) |
| Attachments | Yes (files, images) |
| Threads | Yes |
| Max message length | 2,000 chars (split automatically) |

**Session scoping:** By default, one session per agent (`dm_scope = "main"`). Set `dm_scope = "per-peer"` in `[session]` to scope per Discord user.

---

## Telegram

Adapter: `claw_telegram` (aiogram 3.x)

**Setup**

1. Message `@BotFather` on Telegram, create a bot, get the token
2. For group use, add the bot to a group and grant it message read permissions

**Config**

```toml
[channels.extra.telegram]
token           = "${TELEGRAM_BOT_TOKEN}"
require_mention = true    # default: true
allowed_users   = []      # empty = all users; e.g. ["123456", "789012"]
```

| Key | Type | Default | Description |
|---|---|---|---|
| `token` | string | required | Bot token from BotFather |
| `require_mention` | bool | `true` | In groups, bot must be `@mentioned` to respond. Private DMs always respond. |
| `allowed_users` | list[string] | `[]` | Restrict to specific Telegram user IDs. Empty = accept all users. |

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | Yes (MarkdownV2, auto-escaped) |
| Attachments | Yes (photo, document, voice) |
| Threads | Yes (supergroup topics) |
| Max message length | 4,096 chars |

**Typing indicator:** Sent automatically before each response.

---

## Slack

Adapter: `claw_slack` (slack-bolt async, Socket Mode)

**Setup**

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Under **OAuth & Permissions**, add scopes: `chat:write`, `im:history`, `im:read`, `channels:history`, `app_mentions:read`, `users:info`
3. Under **Socket Mode**, enable it and generate an **App-Level Token** (scope: `connections:write`) — this is the `app_token` (`xapp-...`)
4. Under **Event Subscriptions → Subscribe to Bot Events**, add: `message.im`, `app_mention`
5. Install the app to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`)

**Config**

```toml
[channels.extra.slack]
bot_token       = "${SLACK_BOT_TOKEN}"
app_token       = "${SLACK_APP_TOKEN}"
require_mention = true    # default: true
```

| Key | Type | Default | Description |
|---|---|---|---|
| `bot_token` | string | required | Bot User OAuth Token (`xoxb-...`) |
| `app_token` | string | required | App-Level Token for Socket Mode (`xapp-...`) |
| `require_mention` | bool | `true` | In channels, bot must be `@mentioned`. DMs always respond. |

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | Yes (mrkdwn) |
| Attachments | No (planned) |
| Threads | Yes |
| Max message length | 3,000 chars |

**Connection mode:** Socket Mode only (no public webhook URL needed).

---

## Matrix

Adapter: `claw_matrix` (matrix-nio async)

**Setup**

1. Register a bot account on your Matrix homeserver (or matrix.org)
2. Note the user ID (`@botname:homeserver.org`) and either the password or an access token

**Config**

```toml
[channels.extra.matrix]
homeserver       = "https://matrix.org"
user_id          = "@claw:matrix.org"
password         = "${MATRIX_PASSWORD}"      # use this OR access_token
access_token     = ""                        # preferred for production
require_mention  = true                      # default: true
store_path       = ""                        # defaults to ~/.claw/matrix_store
```

| Key | Type | Default | Description |
|---|---|---|---|
| `homeserver` | string | required | Matrix homeserver URL (e.g. `https://matrix.org`) |
| `user_id` | string | required | Full Matrix user ID (`@bot:homeserver.org`) |
| `password` | string | `""` | Account password. Used if `access_token` is empty. |
| `access_token` | string | `""` | Preferred for production — avoids storing password. |
| `require_mention` | bool | `true` | In rooms, bot must be mentioned (by user ID or local part). DM rooms (m.direct) always respond. |
| `store_path` | string | `""` | Sync store path. Empty = `~/.claw/matrix_store`. |

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | Yes |
| Attachments | No (planned) |
| Threads | Yes (m.relates_to reply threading) |
| E2EE | Not yet (planned via matrix-nio[e2e]) |
| Max message length | 32,000 chars |

---

## Signal

Adapter: `claw_signal` (signal-cli JSON-RPC bridge)

Signal requires an external binary (`signal-cli`) that must be pre-registered with a phone number. This is the most involved setup.

**Setup**

1. Install [signal-cli](https://github.com/AsamK/signal-cli) and ensure it is on `PATH`
2. Register or link a phone number:
   ```bash
   signal-cli -u +14155552671 register
   signal-cli -u +14155552671 verify <code>
   ```
3. Confirm it works: `signal-cli -u +14155552671 receive`

**Config**

```toml
[channels.extra.signal]
phone_number = "+14155552671"
cli_path     = "signal-cli"      # default: signal-cli on PATH
data_path    = ""                # default: ~/.local/share/signal-cli
```

| Key | Type | Default | Description |
|---|---|---|---|
| `phone_number` | string | required | The registered Signal phone number (E.164 format) |
| `cli_path` | string | `"signal-cli"` | Path to the signal-cli binary |
| `data_path` | string | `""` | signal-cli data directory. Empty = signal-cli default (`~/.local/share/signal-cli`) |

**Capabilities**

| Feature | Support |
|---|---|
| Markdown | No (plain text only) |
| Attachments | Yes (received only; not yet sent) |
| Threads | No |
| Max message length | 2,000 chars |

**How it works:** Claw spawns `signal-cli` as a subprocess in `jsonRpc` mode and communicates over stdin/stdout. The subprocess must stay running for the duration of the Claw process.

---

## Routing messages to specific agents

By default all channel messages go to the default agent. Use `[[bindings]]` to route based on channel, guild, peer ID, etc.:

```toml
# All Discord messages from guild 123456789 go to the researcher agent
[[bindings]]
agent_id = "researcher"
[bindings.match]
channel  = "discord"
guild_id = "123456789"

# A specific Telegram user always talks to the coder agent
[[bindings]]
agent_id = "coder"
[bindings.match]
channel = "telegram"
peer_id = "987654321"
```

See [CONFIGURATION.md](CONFIGURATION.md) for the full `[[bindings]]` reference.

---

## Using multiple channels simultaneously

All channel adapters start at gateway startup and run concurrently. Add as many as needed:

```toml
[channels.extra.telegram]
token = "${TELEGRAM_BOT_TOKEN}"

[channels.extra.discord]
token = "${DISCORD_BOT_TOKEN}"

[channels.extra.slack]
bot_token = "${SLACK_BOT_TOKEN}"
app_token = "${SLACK_APP_TOKEN}"
```

Each channel maintains its own connection; a failure in one does not affect others.
