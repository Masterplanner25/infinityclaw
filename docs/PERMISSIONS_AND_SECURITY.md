# Permissions and Security — Infinity Claw

## Why This Document Exists

The moment agents can access files, the security model becomes non-negotiable. An agent with unrestricted filesystem access can read private keys, modify system files, or exfiltrate data. This document defines the permission boundaries that keep Infinity Claw safe by default.

**The core principle: deny by default. Grant explicitly.**

---

## Trust Levels

Infinity Claw operates with three distinct trust principals:

| Principal | Description | Default trust |
|---|---|---|
| Operator | The person running `claw start`; controls config and credentials | Full |
| User | A human interacting via a channel (Telegram, WebChat, etc.) | Scoped to configured agent |
| Agent | The LLM itself, executing tool calls | Minimum necessary |

Trust does not flow upward. A user cannot grant an agent more trust than the user has. An agent cannot grant itself capabilities it was not configured with.

---

## Current Security Model

### Gateway Authentication

Infinity Claw supports three authentication modes for incoming connections:

**1. Open (no auth)**

No `gateway.token` set. All inbound connections accepted. Suitable for local development or trusted-network deployments only.

**2. Static bearer token**

```toml
[gateway]
token = "your-secret-token"
```

All WebSocket connections and HTTP calls must present `Authorization: Bearer <token>` or `X-Claw-Token: <token>`.

**3. JWT + API key (AuthManager)**

Full token issuance and persistent API key management via `POST /auth/token` and `POST /auth/keys`. Keys are stored hashed and can be revoked individually.

```bash
# Issue a JWT
curl -X POST "http://localhost:18789/auth/token?user_id=alice&secret=gateway-secret"

# Create an API key
curl -X POST "http://localhost:18789/auth/keys?label=telegram-bot"

# Revoke an API key
curl -X DELETE "http://localhost:18789/auth/keys/{key_id}"
```

### AINDY Mounted Mode

When Claw runs inside the AINDY platform layer (`aindy.mounted = true`), `GatewayAuth` enters bypass mode. The platform layer has already authenticated the request; Claw trusts the AINDY principal and does not re-verify. All requests are treated as `AuthPrincipal(user_id="aindy", scopes=["*"])`.

---

## Permissions Model *(Phase 7 — complete)*

### Capability Declarations

Each agent declares its capabilities explicitly in `claw.toml`. An agent cannot use a capability that is not declared, regardless of what the LLM requests. Capabilities are enforced in `_run_turn` via `PermissionEnforcer` — built fresh each turn, never cached.

```toml
[[agents.list]]
id = "main"
capabilities = { tool_use = { allow = ["*"], deny = [] }, external_http = { enabled = true } }
```

```toml
[[agents.list]]
id = "readonly-assistant"
capabilities = { external_http = { enabled = false }, tool_use = { allow = ["recall", "browser_fetch"], deny = ["remember", "forget"] } }
```

**Enforcement flow:**
1. `filter_tool_definitions()` strips denied/non-allowed tools before the LLM call — the LLM never sees tools it cannot use
2. `check_tool_call()` re-checks at invocation time — catches any bypass attempt
3. `PermissionDenied` raises → `scoped_executor` returns `{"error": "permission denied: ..."}` as the tool result

---

### Filesystem Permissions

Filesystem access is **disabled by default**. It must be explicitly granted per agent with the minimum necessary scope.

```toml
[agents.list.capabilities]
filesystem = {
    read   = true,
    write  = true,
    delete = false,
    paths  = ["~/projects/my-project"],   # scoped to specific directories
}
```

**Enforced restrictions:**

- Path traversal is blocked. `../../../etc/passwd` style paths are rejected
- Symlink following is disabled unless explicitly enabled
- Operations outside declared `paths` are rejected even if `read = true`
- `delete = false` by default, always

**Never granted without explicit config:**

- Access to system directories (`/etc`, `/var`, `/usr`, `C:\Windows`, etc.)
- Access to credential files (`.env`, `*.key`, `*.pem`, SSH keys)
- Write access to `claw.toml` or other Claw config files

---

### External HTTP Permissions

The `browser_fetch` tool allows agents to make HTTP requests. By default it is enabled with no URL restrictions. In production deployments, restrict this:

```toml
[agents.list.capabilities]
external_http = {
    enabled   = true,
    allowlist = ["https://api.github.com", "https://docs.example.com"],
    denylist  = ["http://internal.corp"],     # deny internal networks
}
```

Private network addresses (`192.168.x.x`, `10.x.x.x`, `172.16.x.x`, `127.x.x.x`, `localhost`, `::1`) are **always blocked** — there is no config switch to allow private network access. This is enforced unconditionally in `_is_private_host()` inside `PermissionEnforcer`.

---

### Memory Permission Scoping

Memory access is per-agent namespaced. By default:

- An agent can read and write its own memory namespace
- An agent cannot read or write another agent's memory namespace
- Cross-agent memory **read** is opt-in via `cross_agent_memory = ["agentA"]` on `[[agents.list]]` (Phase 8). This causes `_run_turn` to also recall `agentA`'s memories and merge them into the system prompt. Write isolation is always enforced — an agent can only write its own namespace.

---

### Tool Permission Scoping

Tools are filtered through an allow/deny list before being presented to the LLM. The LLM cannot call a tool that is not in its declared allow set, even if the tool exists in the global `ToolRegistry`.

```toml
[agents.list.capabilities]
tool_use = { allow = ["remember", "recall"], deny = [] }
# → LLM only sees "remember" and "recall" in its tools list
```

---

### Skill Gating

Skills are filtered by two gates in sequence (Phase 8):

1. **Global gate** — `[skills] allow/deny` in `claw.toml`; applies to all agents
2. **Per-agent gate** — `capabilities.skill_use.allow/deny` on `[[agents.list]]`; applied after the global gate

```toml
[[agents.list]]
id = "restricted"
capabilities = { skill_use = { allow = ["file_read"], deny = ["shell_exec"] } }
```

`["*"]` in the allow list means "all skills that pass the global gate" (wildcard). An empty allow list also means all. Shell execution skills should always appear in the global deny list.

---

## Credential Security

### API Keys and Tokens

- Gateway bearer tokens and Anthropic API keys are stored in `.env` (never committed to source)
- `ANTHROPIC_API_KEY` is consumed from environment at startup; never serialized back to disk
- Claw API keys are stored **hashed** in the SQLite API key store; the raw key is returned once at creation and never retrievable again

### AINDY Credentials

- `AINDY_API_KEY` is consumed from environment; never stored in `claw.toml`
- AINDY connections are TLS (production deployments); plain HTTP is development-only

---

## Security Checklist for Deployment

Before exposing Infinity Claw to untrusted networks:

- [ ] Set `gateway.token` or configure AuthManager (never run open on a public interface)
- [ ] Restrict `external_http` to an allowlist if agents should not make arbitrary HTTP requests
- [ ] Verify `filesystem.read = false` unless you have intentionally granted file access
- [ ] Set `filesystem.paths` to the minimum necessary directories if read is enabled
- [ ] Use HTTPS termination (nginx / Caddy) in front of Claw; never expose plain HTTP externally
- [ ] Rotate `ANTHROPIC_API_KEY` and AINDY credentials on a schedule
- [ ] Enable AINDY execution tracking (Phase 3) so every tool call has an `execution_unit_id` in the audit log

---

## Threat Model

| Threat | Mitigation |
|---|---|
| Prompt injection via user input | Tool calls are validated against allow/deny lists; filesystem paths are validated against declared `paths` |
| SSRF via browser_fetch | Private network addresses blocked by default; URL allowlist available |
| Credential exfiltration | API keys never in context window; env-only credential storage |
| Memory poisoning | Memory nodes are per-agent namespaced; cross-agent write is not possible without explicit config |
| Path traversal | All filesystem paths resolved and validated against declared `paths` before execution |
| Token theft | JWT expiry configured; API keys stored hashed; single-issue raw key |
