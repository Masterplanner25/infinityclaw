"""Claw CLI — start the gateway or run management commands."""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="claw", description="Claw personal AI assistant")
    parser.add_argument("--config", "-c", metavar="PATH", help="Config file path")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    parser.add_argument("--version", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # start
    p_start = sub.add_parser("start", help="Start the Claw gateway (default)")
    p_start.add_argument("--host", metavar="HOST")
    p_start.add_argument("--port", "-p", type=int, metavar="PORT")
    p_start.add_argument("--daemon", "-d", action="store_true", help="Run in background (POSIX only)")

    # stop
    sub.add_parser("stop", help="Stop a running daemon")

    # status
    sub.add_parser("status", help="Show daemon status")

    # check
    sub.add_parser("check", help="Validate config and exit")

    # doctor
    sub.add_parser("doctor", help="Check all subsystems for health issues")

    # agents
    p_agents = sub.add_parser("agents", help="Manage agents")
    ag_sub = p_agents.add_subparsers(dest="agents_cmd")
    ag_sub.add_parser("list", help="List configured agents")
    p_ag_add = ag_sub.add_parser("add", help="Add an agent to the config")
    p_ag_add.add_argument("id", help="Agent ID")
    p_ag_add.add_argument("--name", default="")
    p_ag_add.add_argument("--model", default="claude-sonnet-4-6")
    p_ag_add.add_argument("--default", action="store_true")

    # cron
    p_cron = sub.add_parser("cron", help="Manage cron jobs")
    cron_sub = p_cron.add_subparsers(dest="cron_cmd")
    cron_sub.add_parser("list", help="List cron jobs")
    p_cron_add = cron_sub.add_parser("add", help="Add a cron job")
    p_cron_add.add_argument("--agent", default="main", dest="agent_id")
    p_cron_add.add_argument("--cron", required=True, help='Cron expression e.g. "0 8 * * *"')
    p_cron_add.add_argument("--prompt", required=True)
    p_cron_add.add_argument("--delivery", default="announce", choices=["announce", "webhook", "none"])
    p_cron_add.add_argument("--channel", default="", dest="delivery_channel")
    p_cron_add.add_argument("--peer", default="", dest="delivery_peer")
    p_cron_add.add_argument("--webhook", default="", dest="webhook_url")

    args = parser.parse_args()

    if args.version:
        from claw import __version__
        print(f"claw {__version__}")
        return

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    command = args.command or "start"

    if command == "check":
        _cmd_check(args)
    elif command == "doctor":
        _cmd_doctor(args)
    elif command == "stop":
        _cmd_stop(args)
    elif command == "status":
        _cmd_status(args)
    elif command == "agents":
        _cmd_agents(args)
    elif command == "cron":
        _cmd_cron(args)
    else:
        _cmd_start(args)


# ------------------------------------------------------------------
# Command implementations
# ------------------------------------------------------------------

def _cmd_doctor(args) -> None:
    import asyncio
    from pathlib import Path

    checks: list[tuple[str, str, str]] = []  # (label, status, note)

    def ok(label: str, note: str = "") -> None:
        checks.append((label, "OK  ", note))
        print(f"  [OK]   {label}" + (f"  ({note})" if note else ""))

    def warn(label: str, note: str = "") -> None:
        checks.append((label, "WARN", note))
        print(f"  [WARN] {label}" + (f"  ({note})" if note else ""))

    def fail(label: str, note: str = "") -> None:
        checks.append((label, "FAIL", note))
        print(f"  [FAIL] {label}" + (f"  ({note})" if note else ""))

    print("\nClaw doctor\n")

    # 1. Config
    try:
        from claw.config.loader import load_config
        cfg = load_config(getattr(args, "config", None))
        ok("Config loads", f"{len(cfg.agents.agents)} agents, {len(cfg.credentials)} credentials")
    except Exception as e:
        fail("Config loads", str(e))
        print("\nCannot continue without a valid config.")
        sys.exit(1)

    # 2. LLM credentials
    async def _check_llm():
        try:
            import anthropic
            from claw.agents.registry import AgentRegistry
            reg = AgentRegistry(cfg)
            store = reg.credential_store()
            profiles = store.available()
            if not profiles:
                fail("LLM credentials", "no profiles available")
                return
            p = profiles[0]
            client = anthropic.AsyncAnthropic(api_key=p.api_key)
            resp = await client.messages.create(
                model=p.model,
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            ok("LLM credentials", f"provider={p.provider} model={p.model}")
        except Exception as e:
            msg = str(e)[:80]
            if "401" in msg or "auth" in msg.lower():
                fail("LLM credentials", f"auth error: {msg}")
            elif "rate" in msg.lower():
                warn("LLM credentials", "rate-limited (key is valid)")
            else:
                fail("LLM credentials", msg)

    asyncio.run(_check_llm())

    # 3. Workspace dirs
    from pathlib import Path
    state_dir = Path(cfg.state_dir).expanduser()
    if state_dir.exists():
        ok("State dir", str(state_dir))
    else:
        warn("State dir", f"not yet created — will be at {state_dir}")

    for agent_cfg in (cfg.agents.agents or []):
        ws = state_dir / "agents" / agent_cfg.id / "workspace"
        if ws.exists():
            ok(f"Workspace [{agent_cfg.id}]", str(ws))
        else:
            warn(f"Workspace [{agent_cfg.id}]", "not yet created (will be created on start)")

    # 4. Memory
    if cfg.memory.enabled:
        db_path = cfg.memory.db_path or str(state_dir / "memory.db")
        if Path(db_path).exists():
            ok("Memory DB", db_path)
        else:
            warn("Memory DB", f"will be created at {db_path} on first start")
    else:
        warn("Memory", "disabled (set memory.enabled = true to enable)")

    # 5. Auth
    token = cfg.gateway.token
    if token:
        ok("Auth", "gateway token configured")
    else:
        import os
        if os.environ.get("CLAW_SECRET_KEY") or os.environ.get("CLAW_GATEWAY_TOKEN"):
            ok("Auth", "secret from environment variable")
        else:
            warn("Auth", "running in open mode (no token configured)")

    # 6. Channel configs
    channel_keys = list(cfg.channels.extra.keys())
    if channel_keys:
        ok("Channels configured", ", ".join(channel_keys))
    else:
        warn("Channels", "only WebChat enabled — no external channels configured")

    # 7. Cron jobs
    if cfg.cron:
        ok("Cron jobs", f"{len(cfg.cron)} job(s) configured")
    else:
        warn("Cron jobs", "none configured")

    # 8. httpx (browser tool)
    try:
        import httpx
        ok("Browser tool (httpx)", httpx.__version__)
    except ImportError:
        fail("Browser tool", "httpx not installed — run: pip install httpx")

    # 9. AINDY connectivity
    if cfg.aindy.enabled:
        async def _check_aindy():
            try:
                from claw.aindy.client import _AsyncAINDYClient
                client = _AsyncAINDYClient(cfg.aindy.url, cfg.aindy.api_key)
                reachable = await client.ping()
                if reachable:
                    ok("AINDY connectivity", cfg.aindy.url)
                else:
                    fail("AINDY connectivity", f"unreachable at {cfg.aindy.url}")
            except Exception as e:
                fail("AINDY connectivity", str(e)[:80])
        asyncio.run(_check_aindy())
    else:
        warn("AINDY", "disabled (set aindy.enabled = true to enable)")

    # Summary
    n_ok = sum(1 for _, s, _ in checks if s == "OK  ")
    n_warn = sum(1 for _, s, _ in checks if s == "WARN")
    n_fail = sum(1 for _, s, _ in checks if s == "FAIL")
    print(f"\n  {n_ok} OK  {n_warn} warnings  {n_fail} failures\n")
    if n_fail:
        sys.exit(1)


def _cmd_check(args) -> None:
    try:
        from claw.config.loader import load_config
        config = load_config(getattr(args, "config", None))
        print(f"Config OK")
        print(f"  Agents:      {len(config.agents.agents or [])}")
        print(f"  Credentials: {len(config.credentials)}")
        print(f"  Bindings:    {len(config.bindings)}")
        print(f"  Cron jobs:   {len(config.cron)}")
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_start(args) -> None:
    import uvicorn
    from pathlib import Path
    from claw.config.loader import load_config
    from claw.gateway.server import build_app

    try:
        config = load_config(getattr(args, "config", None))
    except Exception as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        sys.exit(1)

    host = getattr(args, "host", None) or config.gateway.host
    port = getattr(args, "port", None) or config.gateway.port
    config.gateway.host = host
    config.gateway.port = port

    if getattr(args, "daemon", False):
        _daemonize(config)
        return

    app, _ = build_app(config)

    print(f"  Claw gateway  http://{host}:{port}/")
    print(f"  WebSocket     ws://{host}:{port}/ws/chat")
    print(f"  Health        http://{host}:{port}/health")

    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


def _daemonize(config) -> None:
    """Fork the current process into background (POSIX only)."""
    import os
    from pathlib import Path

    if not hasattr(os, "fork"):
        print("Daemon mode is not supported on Windows. Use a process manager instead.", file=sys.stderr)
        sys.exit(1)

    state_dir = Path(config.state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "claw.pid"
    log_file = state_dir / "claw.log"

    pid = os.fork()
    if pid > 0:
        print(f"Claw daemon started (PID {pid})")
        print(f"  Log:  {log_file}")
        print(f"  PID:  {pid_file}")
        return

    # Child: second fork to fully detach
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)

    # Grandchild: redirect stdio, write PID, start server
    import uvicorn
    from claw.gateway.server import build_app

    pid_file.write_text(str(os.getpid()))
    log_fd = open(log_file, "a", buffering=1)
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    app, _ = build_app(config)
    uvicorn.run(app, host=config.gateway.host, port=config.gateway.port, log_level="info")


def _pid_file_path(args=None) -> "Path":
    from pathlib import Path
    try:
        from claw.config.loader import load_config
        cfg = load_config(getattr(args, "config", None) if args else None)
        return Path(cfg.state_dir).expanduser() / "claw.pid"
    except Exception:
        return Path("~/.claw/claw.pid").expanduser()


def _cmd_stop(args) -> None:
    import signal
    from pathlib import Path

    pid_file = _pid_file_path(args)
    if not pid_file.exists():
        print("No PID file found — is Claw running as a daemon?")
        sys.exit(1)

    try:
        pid = int(pid_file.read_text().strip())
        import os
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        print(f"Sent SIGTERM to PID {pid}")
    except ProcessLookupError:
        print(f"Process {pid} not found — removing stale PID file")
        pid_file.unlink(missing_ok=True)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to stop daemon: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_status(args) -> None:
    from pathlib import Path

    pid_file = _pid_file_path(args)
    if not pid_file.exists():
        print("Claw is not running (no PID file)")
        sys.exit(1)

    try:
        pid = int(pid_file.read_text().strip())
        import os
        os.kill(pid, 0)  # signal 0 = check existence
        print(f"Claw is running (PID {pid})")
    except ProcessLookupError:
        print(f"Claw PID file found but process {pid} is not running (stale PID file)")
        sys.exit(1)
    except Exception as exc:
        print(f"Status check failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_agents(args) -> None:
    from claw.config.loader import load_config
    config = load_config(getattr(args, "config", None))
    cmd = getattr(args, "agents_cmd", "list") or "list"

    if cmd == "list":
        agents = config.agents.agents or []
        if not agents:
            print("No agents configured (default: main)")
            return
        for a in agents:
            flags = " [default]" if a.default else ""
            print(f"  {a.id}{flags}  model={a.model.primary}  name={a.name or a.id}")

    elif cmd == "add":
        from claw.config.schema import AgentConfig, ModelConfig
        new_agent = AgentConfig(
            id=args.id,
            name=args.name or args.id,
            default=args.default,
            model=ModelConfig(primary=args.model),
        )
        print(f"Agent config to add to claw.toml:")
        print()
        print(f"[[agents.list]]")
        print(f'id = "{new_agent.id}"')
        print(f'name = "{new_agent.name}"')
        print(f'default = {str(new_agent.default).lower()}')
        print(f'[agents.list.model]')
        print(f'primary = "{new_agent.model.primary}"')


def _cmd_cron(args) -> None:
    from claw.config.loader import load_config
    config = load_config(getattr(args, "config", None))
    cmd = getattr(args, "cron_cmd", "list") or "list"

    if cmd == "list":
        jobs = config.cron or []
        if not jobs:
            print("No cron jobs configured")
            return
        for j in jobs:
            print(f"  [{j.id or '?'}] {j.cron!r}  agent={j.agent_id}  delivery={j.delivery}")
            print(f"       prompt: {j.prompt[:60]}")

    elif cmd == "add":
        print("Cron job config to add to claw.toml:")
        print()
        print(f"[[cron]]")
        print(f'agent_id = "{args.agent_id}"')
        print(f'cron = "{args.cron}"')
        print(f'prompt = "{args.prompt}"')
        print(f'delivery = "{args.delivery}"')
        if args.delivery_channel:
            print(f'delivery_channel = "{args.delivery_channel}"')
        if args.delivery_peer:
            print(f'delivery_peer = "{args.delivery_peer}"')
        if args.webhook_url:
            print(f'webhook_url = "{args.webhook_url}"')


if __name__ == "__main__":
    main()
