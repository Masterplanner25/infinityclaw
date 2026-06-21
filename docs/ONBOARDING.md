# Onboarding — Infinity Claw

This guide takes you from nothing to a running AI workspace in under 10 minutes.

---

## Prerequisites

- Python 3.11 or later
- An Anthropic API key (`ANTHROPIC_API_KEY`)
- Git

That is all. No Docker, no database, no message broker required for a basic deployment.

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/Masterplanner25/infinityclaw.git
cd infinityclaw

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -e .
```

---

## Step 2 — Configure Credentials

```bash
cp .env.example .env
```

Open `.env` and set your Anthropic API key:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Everything else is optional for a first run.

---

## Step 3 — Start the Gateway

```bash
claw start
```

You should see:

```
  Claw gateway  http://127.0.0.1:18789/
  WebSocket     ws://127.0.0.1:18789/ws/chat
  Health        http://127.0.0.1:18789/health
```

---

## Step 4 — Open WebChat

Navigate to `http://127.0.0.1:18789/` in your browser. The built-in WebChat UI connects automatically over WebSocket.

Type a message and press Enter. You should receive a response from the `main` agent.

---

## Step 5 — Connect a Channel (Optional)

To reach Claw from Telegram, add this to your `claw.toml`:

```toml
[channels.extra.telegram]
token = "your-bot-token"
```

Restart Claw (`Ctrl-C` + `claw start`). Your agent is now reachable from both WebChat and Telegram under the same identity, with shared memory.

For other channels (Discord, Slack, Matrix, Signal), see the relevant section in `claw.toml` or refer to each adapter's documentation.

---

## Step 6 — Add a Second Agent (Optional)

Add to `claw.toml`:

```toml
[[agents.list]]
id = "coder"
name = "Claw Coder"

[agents.list.model]
primary    = "claude-haiku-4-5-20251001"
max_tokens = 2048
```

Restart Claw. You now have two agents — `main` (default, general assistant) and `coder` (code-focused). Route users to specific agents via `bindings` in `claw.toml`.

---

## Step 7 — Check Everything Is Working

```bash
claw doctor
```

This runs a health check on all subsystems: config, LLM credentials, workspace directories, memory, auth, channels, and AINDY connectivity.

---

## Step 8 — Create a Workspace

Claw automatically creates a workspace directory for each agent at `~/.claw/agents/{agent_id}/workspace/`. Drop files here — notes, project plans, reference documents — and the agent will have access to them on the next turn.

```bash
# Add a knowledge file to the main agent's workspace
echo "# My Project Notes" > ~/.claw/agents/main/workspace/project.md
echo "We are building X for Y. Key decisions: ..." >> ~/.claw/agents/main/workspace/project.md
```

On the next message, the agent will see this file as part of its context.

---

## Step 9 — Schedule a Cron Job (Optional)

Add to `claw.toml`:

```toml
[[cron]]
id       = "morning-brief"
agent_id = "main"
prompt   = "Produce a brief morning status summary for today."
cron     = "0 9 * * 1-5"     # 9 AM weekdays
delivery = "announce"
```

Restart Claw. Every weekday at 9 AM, the agent will run this prompt and send the result to the configured delivery channel.

---

## Step 10 — Enable AINDY (Optional)

If you have an AINDY runtime:

```toml
[aindy]
enabled        = true
url            = "http://localhost:8000"
memory_backend = "aindy-fallback"
emit_events    = true
```

And set `AINDY_API_KEY` in `.env`. AINDY provides distributed memory, turn lifecycle events, and integration with the Masterplan Infinite Weave platform.

---

## Verify the Test Suite

After installation, confirm everything is wired correctly:

```bash
pytest tests/ -q
```

All tests should pass. The test suite runs against the real FastAPI ASGI app with in-memory SQLite — no mocks, no network.

---

## Common First-Run Issues

**`RuntimeError: No LLM credentials available`**

`.env` not loaded or `ANTHROPIC_API_KEY` not set. Confirm with:

```bash
echo $ANTHROPIC_API_KEY       # macOS / Linux
$env:ANTHROPIC_API_KEY        # Windows PowerShell
```

**Port 18789 already in use**

Change the port in `claw.toml`:

```toml
[gateway]
port = 18790
```

**WebChat UI shows "Connection failed"**

Check that Claw is running (`claw status`) and that you're connecting to the correct port.

**`claw doctor` shows memory DB warning**

Expected on first run. The SQLite database is created automatically on the first memory write.
