# Deployment — Infinity Claw

This document covers running Claw in production: configuration, process management, auth setup, and the two deployment modes (standalone and AINDY-mounted).

---

## Deployment modes

### Standalone mode (default)

Claw runs as its own FastAPI/Uvicorn process. This is the mode used when you run `claw start`. It includes:

- Full HTTP server on a configurable host and port
- `/health` and `/ready` liveness/readiness endpoints
- Prometheus metrics (via `nodus_observability_framework` if installed)
- WebChat UI at `GET /`
- All configured channel adapters

This is the correct mode for personal use, self-hosted deployments, and Weave peer nodes.

### AINDY mounted mode

Claw's routes are registered inside the AINDY platform layer instead of running a standalone server. In this mode:

- Claw has no HTTP server of its own
- Auth is handled upstream by AINDY
- `/health` and `/ready` are suppressed (AINDY provides them)
- Entry point is `claw.aindy.app_registration.register_claw_app()`, not `claw start`

Enable with `aindy.mounted = true` in `claw.toml`. Running `claw start` in mounted mode prints a warning and continues in standalone mode (suppressing health routes only).

---

## Prerequisites

- Python 3.11 or later
- An Anthropic API key
- `pip install -e .` run from the repo root (or `pip install infinityclaw` for a package install)

No database server, message broker, or container runtime is required for a basic deployment. All state is SQLite files in `state_dir` (default `~/.claw/`).

---

## Config file

Claw reads `claw.toml` from the current working directory by default. Override with:

```powershell
claw start --config /path/to/claw.toml
```

Or set the path in the environment if you wrap `claw start` in a script. See [CONFIGURATION.md](CONFIGURATION.md) for the full schema.

---

## State directory

All runtime state lives under `state_dir` (default `~/.claw/`):

```
~/.claw/
  memory.db          # agent memories (SQLite)
  knowledge.db       # FTS5 knowledge index (SQLite)
  workspace.db       # workspace objects (SQLite)
  weave.db           # peer node registry (SQLite)
  node_id            # persistent Weave node UUID
  claw.pid           # PID file (daemon mode, POSIX only)
  claw.log           # log file (daemon mode)
  agents/
    main/
      workspace/     # files available to the main agent
    researcher/
      workspace/
```

Change `state_dir` in `claw.toml` to relocate all of this:

```toml
state_dir = "/var/lib/claw"
```

---

## Auth setup

By default, Claw runs in open mode — no credentials required. For any network-exposed deployment, set a token:

```toml
[gateway]
token = "your-strong-secret-here"
```

Or via environment variable (preferred for production):

```powershell
$env:CLAW_GATEWAY_TOKEN = "your-strong-secret-here"
claw start
```

With a token set, clients must supply `Authorization: Bearer <token>` on all HTTP requests and WebSocket upgrades.

### API keys

For multi-client setups, issue per-client API keys instead of sharing the static token:

```powershell
# Issue a key (gateway must be running)
curl -X POST "http://localhost:18789/auth/keys?label=my-client" \
  -H "Authorization: Bearer your-strong-secret-here"
```

The returned `key` value is the credential clients use. Keys can be revoked individually via `DELETE /auth/keys/{key_id}`.

---

## Binding to a public address

To accept connections from outside localhost:

```toml
[gateway]
host  = "0.0.0.0"
port  = 18789
token = "your-secret"
```

Put a reverse proxy (nginx, Caddy) in front for TLS termination in internet-facing deployments.

**nginx example:**

```nginx
server {
    listen 443 ssl;
    server_name claw.example.com;

    ssl_certificate     /etc/ssl/claw.crt;
    ssl_certificate_key /etc/ssl/claw.key;

    location / {
        proxy_pass http://127.0.0.1:18789;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
    }
}
```

The `Upgrade` and `Connection` headers are required for WebSocket proxying.

---

## Process management

### Windows

Daemon mode (`claw start --daemon`) is not supported on Windows. Use one of:

**Task Scheduler** — create a task that runs `claw start` at login or on a schedule.

**pm2** (Node.js process manager, works for any process):

```powershell
npm install -g pm2
pm2 start "claw start" --name claw --interpreter none
pm2 save
pm2 startup
```

**NSSM** (Non-Sucking Service Manager):

```powershell
nssm install claw "C:\dev\claw\venv\Scripts\python.exe" "-m claw start"
nssm set claw AppDirectory C:\dev\claw
nssm start claw
```

### Linux / macOS

**systemd** (recommended):

```ini
# /etc/systemd/system/claw.service
[Unit]
Description=Infinity Claw Gateway
After=network.target

[Service]
Type=simple
User=claw
WorkingDirectory=/home/claw/claw
Environment=ANTHROPIC_API_KEY=sk-ant-...
Environment=CLAW_GATEWAY_TOKEN=your-secret
ExecStart=/home/claw/claw/venv/bin/python -m claw start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable claw
sudo systemctl start claw
sudo journalctl -u claw -f   # tail logs
```

**Daemon mode** (POSIX only, simple deployments):

```bash
claw start --daemon
# Logs go to ~/.claw/claw.log
# PID is in ~/.claw/claw.pid

claw status   # check if running
claw stop     # send SIGTERM
```

---

## Health checks

When running in standalone mode:

```bash
# Liveness
curl http://localhost:18789/health
# {"status":"ok","service":"claw-gateway"}

# Readiness
curl http://localhost:18789/ready
# {"status":"ready"}
```

For a deeper check of all subsystems:

```bash
claw doctor
```

This validates config, LLM credentials (live API call), workspace directories, memory DB, auth, channels, and AINDY connectivity.

---

## Enabling optional subsystems

All optional subsystems are disabled by default. Enable them incrementally:

```toml
# Memory — persist agent recall across sessions
[memory]
enabled = true

# Knowledge — index workspace files for RAG
[knowledge]
enabled = true
top_k   = 5

# Workspace objects — Documents and Tasks per agent
[workspace]
enabled = true

# Multi-agent coordination — delegate_to_agent tool
[coordination]
enabled = true

# Weave — distributed peer networking
[weave]
enabled = true
```

After enabling a new subsystem, restart Claw. The required SQLite databases are created automatically on first startup.

---

## Multiple Claw instances (Weave)

To form a Weave network, run Claw on two or more machines and connect the nodes:

**Node A** (`http://node-a:18789`):
```toml
[weave]
enabled = true
```

**Node B** (`http://node-b:18789`):
```toml
[weave]
enabled = true
```

Connect Node A to Node B (run on Node A):

```powershell
claw weave connect http://node-b:18789 --label "Node B"
```

This fetches Node B's `node_id` and registers it locally. Repeat in the other direction if you want bidirectional agent access.

```powershell
# On Node B:
claw weave connect http://node-a:18789 --label "Node A"
```

Verify:

```powershell
claw weave status   # shows local node_id + peer count
claw weave nodes    # lists registered peers
```

If Node B requires auth:

```powershell
claw weave connect http://node-b:18789 --key "node-b-token"
```

---

## AINDY mounted mode

For use inside the AINDY platform layer:

```toml
[aindy]
enabled = true
mounted = true
url     = "http://localhost:8000"
api_key = "${AINDY_API_KEY}"
```

Entry point (called by the AINDY platform, not `claw start`):

```python
from claw.aindy.app_registration import register_claw_app

gateway = await register_claw_app(
    config_path="claw.toml",
    prefix="/claw",   # prefix applied by the platform layer
)
```

`register_claw_app()` starts the gateway, builds the router, and calls `AINDY.platform_layer.registry.register_router(router)`. The `prefix` parameter is applied by the platform layer caller — do not include it in route definitions.

---

## Log levels

Set in `claw.toml` or at runtime:

```toml
log_level = "info"   # debug | info | warning | error
```

```powershell
claw start --log-level debug
```

---

## Known limitations

| Limitation | Notes |
|---|---|
| Daemon mode | POSIX only (`os.fork`). On Windows, use a process manager. |
| `claw weave connect` requires live remote | Always calls `GET /weave/agents` to fetch node ID. Offline registration is not supported. |
| Knowledge watcher | Requires `watchfiles` (included in default install). If missing, auto-reindex is silently skipped; use `claw workspace index` manually. |
| TLS | Not handled natively. Use a reverse proxy for HTTPS/WSS. |
