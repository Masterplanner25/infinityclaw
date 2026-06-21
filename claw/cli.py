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

    # workspace
    p_workspace = sub.add_parser("workspace", help="Manage workspace files and objects")
    ws_sub = p_workspace.add_subparsers(dest="workspace_cmd")
    p_ws_index = ws_sub.add_parser("index", help="Index workspace files for knowledge retrieval")
    p_ws_index.add_argument("--agent", default="", dest="agent_id", metavar="ID",
                            help="Agent to index (default: all agents)")
    p_ws_create = ws_sub.add_parser("create", help="Create a workspace object store for an agent")
    p_ws_create.add_argument("name", help="Workspace name")
    p_ws_create.add_argument("--description", default="", help="Optional description")
    p_ws_create.add_argument("--agent", default="main", dest="agent_id", metavar="ID",
                             help="Agent ID that owns this workspace (default: main)")
    ws_sub.add_parser("list", help="List all workspace objects")
    p_ws_share = ws_sub.add_parser("share", help="Grant an agent access to a workspace")
    p_ws_share.add_argument("workspace_id", help="Workspace ID to share")
    p_ws_share.add_argument("--agent", required=True, dest="agent_id", metavar="ID",
                            help="Agent ID to grant access to")
    p_ws_share.add_argument("--perm", default="read", dest="level",
                            choices=["none", "read", "write"],
                            help="Permission level (default: read)")

    # backup
    p_backup = sub.add_parser("backup", help="Archive all data stores to a .tar.gz file")
    p_backup.add_argument("--output", "-o", metavar="PATH", default="",
                          help="Output archive path (default: claw-backup-<timestamp>.tar.gz)")

    # restore
    p_restore = sub.add_parser("restore", help="Restore data stores from a backup archive")
    p_restore.add_argument("archive", metavar="ARCHIVE", help="Path to .tar.gz backup archive")

    # weave
    p_weave = sub.add_parser("weave", help="Manage distributed Weave node connections")
    weave_sub = p_weave.add_subparsers(dest="weave_cmd")
    weave_sub.add_parser("status", help="Show local node ID and peer count")
    weave_sub.add_parser("nodes", help="List registered peer nodes")
    p_weave_connect = weave_sub.add_parser("connect", help="Register a remote peer node")
    p_weave_connect.add_argument("url", help="Base URL of the remote Claw gateway")
    p_weave_connect.add_argument("--label", default="", help="Human-readable label")
    p_weave_connect.add_argument("--key", default="", dest="api_key", help="API key for the remote node")
    p_weave_connect.add_argument("--no-ping", action="store_true", dest="no_ping",
                                 help="Skip reachability ping before registering")
    p_weave_disconnect = weave_sub.add_parser("disconnect", help="Remove a registered peer node")
    p_weave_disconnect.add_argument("node_id", help="Node ID to remove")

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
    elif command == "backup":
        _cmd_backup(args)
    elif command == "restore":
        _cmd_restore(args)
    elif command == "stop":
        _cmd_stop(args)
    elif command == "status":
        _cmd_status(args)
    elif command == "agents":
        _cmd_agents(args)
    elif command == "workspace":
        _cmd_workspace(args)
    elif command == "weave":
        _cmd_weave(args)
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

    # 10. DB integrity checks
    def _run_integrity(db_path_cfg: str, default_name: str, label: str) -> None:
        db = db_path_cfg or str(state_dir / default_name)
        if not Path(db).exists():
            return
        if _db_integrity_ok(db):
            ok(f"{label} integrity", db)
        else:
            fail(f"{label} integrity", f"PRAGMA integrity_check failed for {db}")

    if cfg.memory.enabled:
        _run_integrity(cfg.memory.db_path, "memory.db", "Memory DB")
    if cfg.workspace.enabled:
        _run_integrity(cfg.workspace.db_path, "workspace.db", "Workspace DB")
    if cfg.weave.enabled:
        _run_integrity(cfg.weave.db_path, "weave.db", "Weave DB")

    # 11. Weave peer reachability
    if cfg.weave.enabled:
        weave_db = cfg.weave.db_path or str(state_dir / "weave.db")
        if Path(weave_db).exists():
            from claw.weave.model import get_or_create_node_id
            from claw.weave.registry import WeaveNodeStore
            from claw.weave.client import WeaveClient

            node_id = get_or_create_node_id(cfg.weave.node_id, str(state_dir))
            ws = WeaveNodeStore(weave_db)
            peers = ws.list_nodes()
            ws.close()

            if not peers:
                ok("Weave peers", "no peers registered")
            else:
                client = WeaveClient(node_id)

                async def _check_peers():
                    for node in peers:
                        reachable = await client.ping(node)
                        short_id = node.node_id[:12]
                        if reachable:
                            ok(f"Weave peer [{short_id}]", node.url)
                        else:
                            warn(f"Weave peer [{short_id}]", f"unreachable at {node.url}")
                asyncio.run(_check_peers())

    # 12. Config consistency
    for msg in _check_config_consistency(cfg):
        warn("Config", msg)

    # Summary
    n_ok = sum(1 for _, s, _ in checks if s == "OK  ")
    n_warn = sum(1 for _, s, _ in checks if s == "WARN")
    n_fail = sum(1 for _, s, _ in checks if s == "FAIL")
    print(f"\n  {n_ok} OK  {n_warn} warnings  {n_fail} failures\n")
    if n_fail:
        sys.exit(1)


def _db_integrity_ok(db_path: str) -> bool:
    """Return True if the SQLite DB at db_path passes PRAGMA integrity_check."""
    import sqlite3 as _sq
    from pathlib import Path as _Path
    if not _Path(db_path).exists():
        return False
    try:
        conn = _sq.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        return bool(result and result[0] == "ok")
    except Exception:
        return False


def _check_config_consistency(cfg) -> list[str]:
    """Return a list of warning strings for config inconsistencies."""
    warnings: list[str] = []

    if cfg.aindy.memory_backend in ("aindy", "aindy-fallback") and not cfg.aindy.enabled:
        warnings.append(
            f"memory_backend={cfg.aindy.memory_backend!r} but aindy.enabled = false "
            "- operations will fall back to SQLite"
        )

    def _looks_inline(value: str) -> bool:
        if not value:
            return False
        if value.startswith("$"):
            return False
        placeholders = {"YOUR_KEY_HERE", "CHANGE_ME", "TODO", "PLACEHOLDER", "SECRET"}
        if any(p in value.upper() for p in placeholders):
            return False
        return True

    secret_fields: list[tuple[str, str]] = []
    if cfg.gateway.token:
        secret_fields.append(("gateway.token", cfg.gateway.token))
    if cfg.aindy.api_key:
        secret_fields.append(("aindy.api_key", cfg.aindy.api_key))
    for cred in cfg.credentials:
        secret_fields.append((f"credentials[{cred.id}].api_key", cred.api_key))

    for field_name, value in secret_fields:
        if _looks_inline(value):
            warnings.append(
                f"Secret inline: {field_name} - "
                "consider an environment variable for production use"
            )

    return warnings


def _cmd_backup(args) -> None:
    import json
    import shutil
    import sqlite3
    import tarfile
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    from claw import __version__
    from claw.config.loader import load_config
    from claw.memory.sqlite_store import SCHEMA_VERSION as MEM_VER
    from claw.weave.registry import SCHEMA_VERSION as WEAVE_VER
    from claw.workspace.store import SCHEMA_VERSION as WS_VER

    cfg = load_config(getattr(args, "config", None))
    state_dir = Path(cfg.state_dir).expanduser()

    def _get_db_schema_version(path: Path) -> int:
        try:
            conn = sqlite3.connect(str(path))
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            conn.close()
            return row[0] if row else 0
        except Exception:
            return 0

    stores: dict[str, dict] = {}
    candidates = [
        ("memory",    cfg.memory.enabled,    cfg.memory.db_path,    "memory.db",    MEM_VER),
        ("workspace", cfg.workspace.enabled,  cfg.workspace.db_path, "workspace.db", WS_VER),
        ("weave",     cfg.weave.enabled,      cfg.weave.db_path,     "weave.db",     WEAVE_VER),
    ]
    for name, enabled, db_path_cfg, default_name, expected_ver in candidates:
        if not enabled:
            continue
        path = Path(db_path_cfg) if db_path_cfg else state_dir / default_name
        if not path.exists():
            print(f"  [SKIP] {name}: {path} not found (never written)")
            continue
        stores[name] = {"path": path, "schema_version": _get_db_schema_version(path)}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = getattr(args, "output", "") or f"claw-backup-{ts}.tar.gz"

    manifest = {
        "claw_version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stores": {name: {"schema_version": info["schema_version"]} for name, info in stores.items()},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
        for name, info in stores.items():
            shutil.copy2(info["path"], tmp / f"{name}.db")
        with tarfile.open(output, "w:gz") as tar:
            tar.add(tmp / "manifest.json", arcname="manifest.json")
            for name in stores:
                tar.add(tmp / f"{name}.db", arcname=f"{name}.db")

    print(f"Backup created: {output}")
    if stores:
        print(f"  Stores: {', '.join(stores.keys())}")
    else:
        print("  No enabled stores had data to back up.")


def _cmd_restore(args) -> None:
    import json
    import sqlite3
    import tarfile
    from pathlib import Path

    from claw.config.loader import load_config
    from claw.memory.sqlite_store import SCHEMA_VERSION as MEM_VER
    from claw.weave.registry import SCHEMA_VERSION as WEAVE_VER
    from claw.workspace.store import SCHEMA_VERSION as WS_VER

    cfg = load_config(getattr(args, "config", None))
    state_dir = Path(cfg.state_dir).expanduser()
    archive_path = args.archive

    if not Path(archive_path).exists():
        print(f"Archive not found: {archive_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            if "manifest.json" not in names:
                print("Invalid archive: missing manifest.json", file=sys.stderr)
                sys.exit(1)

            manifest_f = tar.extractfile("manifest.json")
            if manifest_f is None:
                print("Invalid archive: could not read manifest.json", file=sys.stderr)
                sys.exit(1)
            manifest = json.loads(manifest_f.read())

            current_versions = {"memory": MEM_VER, "workspace": WS_VER, "weave": WEAVE_VER}
            for name, info in manifest.get("stores", {}).items():
                backup_ver = info.get("schema_version", 0)
                current_ver = current_versions.get(name, 0)
                if backup_ver != current_ver:
                    print(
                        f"Schema version mismatch for '{name}': "
                        f"backup={backup_ver}, current={current_ver}. "
                        "Upgrade your Claw installation before restoring.",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            db_paths = {
                "memory":    Path(cfg.memory.db_path)    if cfg.memory.db_path    else state_dir / "memory.db",
                "workspace": Path(cfg.workspace.db_path) if cfg.workspace.db_path else state_dir / "workspace.db",
                "weave":     Path(cfg.weave.db_path)     if cfg.weave.db_path     else state_dir / "weave.db",
            }

            restored = []
            for name in manifest.get("stores", {}):
                archive_name = f"{name}.db"
                if archive_name not in names:
                    print(f"  [SKIP] {name}: missing from archive")
                    continue
                target = db_paths.get(name)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                member_f = tar.extractfile(archive_name)
                if member_f is None:
                    print(f"  [SKIP] {name}: could not read from archive")
                    continue
                target.write_bytes(member_f.read())
                restored.append(f"{name} -> {target}")

    except tarfile.TarError as exc:
        print(f"Failed to open archive: {exc}", file=sys.stderr)
        sys.exit(1)

    if restored:
        print("Restore complete:")
        for line in restored:
            print(f"  {line}")
    else:
        print("No stores were restored (archive may be empty or stores not enabled).")


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

    if config.aindy.mounted:
        print(
            "WARNING: aindy.mounted = true in config.\n"
            "  Standalone 'claw start' is not the intended entry point in mounted mode.\n"
            "  Use claw.aindy.app_registration.register_claw_app() to mount Claw\n"
            "  inside the AINDY platform layer instead.\n"
            "  Continuing in standalone mode — health/observability routes are suppressed.",
            file=sys.stderr,
        )

    if getattr(args, "daemon", False):
        _daemonize(config)
        return

    app, _ = build_app(config)

    print(f"  Claw gateway  http://{host}:{port}/")
    print(f"  WebSocket     ws://{host}:{port}/ws/chat")
    if not config.aindy.mounted:
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


def _cmd_workspace(args) -> None:
    from claw.config.loader import load_config
    config = load_config(getattr(args, "config", None))
    cmd = getattr(args, "workspace_cmd", None)

    if cmd == "create":
        _cmd_workspace_create(args, config)
    elif cmd == "list":
        _cmd_workspace_list(args, config)
    elif cmd == "share":
        _cmd_workspace_share(args, config)
    elif cmd == "index" or cmd is None:
        if not config.knowledge.enabled:
            print("Knowledge layer is disabled.")
            print("Set [knowledge] enabled = true in claw.toml to enable it.")
            sys.exit(1)

        from pathlib import Path
        from claw.knowledge.index import KnowledgeIndex
        from claw.knowledge.scanner import WorkspaceScanner
        from claw.knowledge.ingestion import ingest_file

        state_dir = Path(config.state_dir).expanduser()
        db_path = config.knowledge.db_path or str(state_dir / "knowledge.db")
        idx = KnowledgeIndex(db_path)
        scanner = WorkspaceScanner()

        agents = config.agents.agents or []
        agent_id_filter = getattr(args, "agent_id", "")
        targets = [a.id for a in agents if not agent_id_filter or a.id == agent_id_filter]

        if not targets:
            print(f"No agent found with id={agent_id_filter!r}")
            idx.close()
            sys.exit(1)

        for agent_id in targets:
            ws_dir = state_dir / "agents" / agent_id / "workspace"
            if not ws_dir.exists():
                print(f"  [SKIP] {agent_id}: workspace not found at {ws_dir}")
                continue
            files = scanner.scan(ws_dir)
            total_chunks = 0
            for path in files:
                chunks = ingest_file(
                    path,
                    workspace_id=agent_id,
                    chunk_size=config.knowledge.chunk_size,
                    chunk_overlap=config.knowledge.chunk_overlap,
                )
                if chunks:
                    idx.clear_source(str(path), agent_id)
                    idx.upsert_many(chunks)
                    total_chunks += len(chunks)
                    print(f"  [OK] [{agent_id}] {path.name}: {len(chunks)} chunk(s)")
                else:
                    print(f"  [SKIP] [{agent_id}] {path.name}: no content extracted")
            print(f"  Total [{agent_id}]: {len(files)} file(s), {total_chunks} chunk(s) indexed")

        idx.close()


def _cmd_workspace_create(args, config) -> None:
    import asyncio
    from pathlib import Path
    from claw.workspace.model import Workspace
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    if not config.workspace.enabled:
        print("Workspace objects are disabled.")
        print("Set [workspace] enabled = true in claw.toml to enable them.")
        sys.exit(1)

    state_dir = Path(config.state_dir).expanduser()
    db_path = config.workspace.db_path or str(state_dir / "workspace.db")
    store = WorkspaceStore(db_path)
    manager = WorkspaceManager(store)

    agent_id = getattr(args, "agent_id", "main") or "main"
    name = getattr(args, "name", "")
    description = getattr(args, "description", "") or ""

    async def _create():
        ws = Workspace(id=agent_id, name=name, description=description, owner_agent_id=agent_id)
        created = await manager.create_workspace(ws)
        print(f"Workspace created:")
        print(f"  id          = {created.id}")
        print(f"  name        = {created.name}")
        print(f"  owner       = {created.owner_agent_id}")
        if created.description:
            print(f"  description = {created.description}")

    asyncio.run(_create())
    store.close()


def _cmd_workspace_list(args, config) -> None:
    import asyncio
    from pathlib import Path
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    if not config.workspace.enabled:
        print("Workspace objects are disabled.")
        print("Set [workspace] enabled = true in claw.toml to enable them.")
        sys.exit(1)

    state_dir = Path(config.state_dir).expanduser()
    db_path = config.workspace.db_path or str(state_dir / "workspace.db")
    store = WorkspaceStore(db_path)
    manager = WorkspaceManager(store)

    async def _list():
        workspaces = await manager.list_workspaces()
        if not workspaces:
            print("No workspaces found.")
            return
        for ws in workspaces:
            print(f"  [{ws.id}]  name={ws.name!r}  owner={ws.owner_agent_id}"
                  + (f"  desc={ws.description!r}" if ws.description else ""))

    asyncio.run(_list())
    store.close()


def _cmd_workspace_share(args, config) -> None:
    import asyncio
    from pathlib import Path
    from claw.workspace.model import WorkspacePermission
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    if not config.workspace.enabled:
        print("Workspace objects are disabled.")
        print("Set [workspace] enabled = true in claw.toml to enable them.")
        sys.exit(1)

    state_dir = Path(config.state_dir).expanduser()
    db_path = config.workspace.db_path or str(state_dir / "workspace.db")
    store = WorkspaceStore(db_path)
    manager = WorkspaceManager(store)

    workspace_id = getattr(args, "workspace_id", "")
    agent_id = getattr(args, "agent_id", "")
    level = getattr(args, "level", "read")

    async def _share():
        ws = await manager.get_workspace(workspace_id)
        if not ws:
            print(f"Workspace {workspace_id!r} not found.")
            sys.exit(1)
        perm = WorkspacePermission(workspace_id=workspace_id, agent_id=agent_id, level=level)
        await manager.set_permission(perm)
        print(f"Permission set: agent={agent_id!r} -> workspace={workspace_id!r} level={level!r}")

    asyncio.run(_share())
    store.close()


def _cmd_weave(args) -> None:
    from claw.config.loader import load_config
    config = load_config(getattr(args, "config", None))
    cmd = getattr(args, "weave_cmd", "status") or "status"

    if not config.weave.enabled:
        print("Weave is disabled.")
        print("Set [weave] enabled = true in claw.toml to enable it.")
        sys.exit(1)

    if cmd == "status":
        _cmd_weave_status(args, config)
    elif cmd == "nodes":
        _cmd_weave_nodes(args, config)
    elif cmd == "connect":
        _cmd_weave_connect(args, config)
    elif cmd == "disconnect":
        _cmd_weave_disconnect(args, config)
    else:
        _cmd_weave_status(args, config)


def _cmd_weave_status(args, config) -> None:
    from pathlib import Path
    from claw.weave.model import get_or_create_node_id
    from claw.weave.registry import WeaveNodeStore

    state_dir = Path(config.state_dir).expanduser()
    node_id = get_or_create_node_id(config.weave.node_id, str(state_dir))
    db_path = config.weave.db_path or str(state_dir / "weave.db")

    peer_count = 0
    if Path(db_path).exists():
        store = WeaveNodeStore(db_path)
        peer_count = len(store.list_nodes())
        store.close()

    print(f"Weave node")
    print(f"  node_id = {node_id}")
    print(f"  peers   = {peer_count}")


def _cmd_weave_nodes(args, config) -> None:
    from pathlib import Path
    from claw.weave.registry import WeaveNodeStore

    state_dir = Path(config.state_dir).expanduser()
    db_path = config.weave.db_path or str(state_dir / "weave.db")

    if not Path(db_path).exists():
        print("No peer nodes registered.")
        return

    store = WeaveNodeStore(db_path)
    nodes = store.list_nodes()
    store.close()

    if not nodes:
        print("No peer nodes registered.")
        return

    for n in nodes:
        label_str = f"  label={n.label!r}" if n.label else ""
        print(f"  {n.node_id}  {n.url}{label_str}")


def _cmd_weave_connect(args, config) -> None:
    import asyncio
    from pathlib import Path
    from claw.weave.model import get_or_create_node_id, WeaveNode
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    state_dir = Path(config.state_dir).expanduser()
    node_id = get_or_create_node_id(config.weave.node_id, str(state_dir))
    db_path = config.weave.db_path or str(state_dir / "weave.db")

    url = args.url.rstrip("/")
    label = getattr(args, "label", "") or ""
    api_key = getattr(args, "api_key", "") or ""
    skip_ping = getattr(args, "no_ping", False)

    client = WeaveClient(local_node_id=node_id)

    async def _fetch_node_id() -> str:
        import httpx
        headers: dict = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                r = await hc.get(f"{url}/weave/agents", headers=headers)
                r.raise_for_status()
                return r.json().get("node_id", "")
        except Exception as exc:
            print(f"  Could not fetch remote node_id: {exc}", file=sys.stderr)
            return ""

    async def _connect():
        remote_node_id = await _fetch_node_id()
        if not remote_node_id:
            print(f"Failed to retrieve remote node ID from {url}/weave/agents — is the remote gateway running?")
            sys.exit(1)

        remote = WeaveNode(node_id=remote_node_id, url=url, label=label, api_key=api_key)

        if not skip_ping:
            reachable = await client.ping(remote)
            if not reachable:
                print(f"Remote node at {url} is not reachable. Use --no-ping to register anyway.")
                sys.exit(1)

        store = WeaveNodeStore(db_path)
        store.register(remote)
        store.close()
        print(f"Peer node registered:")
        print(f"  node_id = {remote_node_id}")
        print(f"  url     = {url}")
        if label:
            print(f"  label   = {label}")

    asyncio.run(_connect())


def _cmd_weave_disconnect(args, config) -> None:
    from pathlib import Path
    from claw.weave.registry import WeaveNodeStore

    state_dir = Path(config.state_dir).expanduser()
    db_path = config.weave.db_path or str(state_dir / "weave.db")
    node_id = args.node_id

    if not Path(db_path).exists():
        print(f"No weave database found. Node {node_id!r} was not registered.")
        sys.exit(1)

    store = WeaveNodeStore(db_path)
    removed = store.remove(node_id)
    store.close()

    if removed:
        print(f"Peer node {node_id!r} removed.")
    else:
        print(f"Node {node_id!r} not found in registry.")
        sys.exit(1)


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
