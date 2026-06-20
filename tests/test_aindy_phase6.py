"""AINDY Phase 6 milestone test — Workspace as First-Class Object.

Tests (no real server or AINDY needed):
- WorkspaceConfig present in ClawConfig with correct defaults
- Workspace, Document, Task, Asset, WorkspacePermission data models
- WorkspaceStore (:memory:) — workspace CRUD
- WorkspaceStore — document upsert/get/list
- WorkspaceStore — task create/get/update/list (with status filter)
- WorkspaceStore — asset create/list
- WorkspaceStore — permission set/get/list
- WorkspaceManager — async wrappers (ensure_workspace idempotent)
- WorkspaceManager — can_read / can_write permission checks
- Workspace tools — ws_create_task, ws_list_tasks, ws_update_task
- Workspace tools — ws_create_document, ws_list_documents, ws_get_document
- is_workspace_tool() helper
- ClawGateway initializes workspace_manager when workspace.enabled = true
- ClawGateway workspace_manager is None when workspace.enabled = false
- CLI workspace create/list/share exit with error when workspace disabled

Run:  python tests/test_aindy_phase6.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# 1. WorkspaceConfig in ClawConfig
# ------------------------------------------------------------------

def test_workspace_config() -> None:
    print("\n== WorkspaceConfig ==")
    try:
        from claw.config.schema import ClawConfig, WorkspaceConfig

        cfg = ClawConfig()
        assert hasattr(cfg, "workspace"), "ClawConfig missing .workspace"
        assert isinstance(cfg.workspace, WorkspaceConfig)
        check("ClawConfig.workspace field present", PASS)

        assert cfg.workspace.enabled is False
        assert cfg.workspace.db_path == ""
        check("WorkspaceConfig defaults", PASS)

        custom = WorkspaceConfig(enabled=True, db_path="/tmp/ws.db")
        assert custom.enabled is True and custom.db_path == "/tmp/ws.db"
        check("WorkspaceConfig custom values", PASS)

    except Exception as exc:
        check("WorkspaceConfig", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Data models
# ------------------------------------------------------------------

def test_data_models() -> None:
    print("\n== Data Models ==")
    try:
        from claw.workspace.model import Workspace, Document, Task, Asset, WorkspacePermission

        ws = Workspace(name="My Workspace", owner_agent_id="main")
        assert ws.id and ws.name == "My Workspace" and ws.owner_agent_id == "main"
        assert ws.description == ""
        check("Workspace model defaults", PASS)

        doc = Document(workspace_id="ws1", name="notes.md", body="# Hello")
        assert doc.id and doc.workspace_id == "ws1" and doc.content_type == "text"
        check("Document model defaults", PASS)

        task = Task(workspace_id="ws1", title="Write tests")
        assert task.id and task.status == "open" and task.priority == 0
        check("Task model defaults", PASS)

        # Status enum validation
        try:
            Task(workspace_id="ws1", title="Bad", status="invalid")  # type: ignore
            check("Task invalid status rejected", FAIL, "expected ValidationError")
        except Exception:
            check("Task invalid status rejected", PASS)

        asset = Asset(workspace_id="ws1", name="logo.png", path="/tmp/logo.png")
        assert asset.id and asset.content_type == "binary" and asset.size_bytes == 0
        check("Asset model defaults", PASS)

        perm = WorkspacePermission(workspace_id="ws1", agent_id="agent2")
        assert perm.level == "read"
        check("WorkspacePermission model defaults", PASS)

        # Permission level validation
        try:
            WorkspacePermission(workspace_id="w", agent_id="a", level="admin")  # type: ignore
            check("WorkspacePermission invalid level rejected", FAIL, "expected ValidationError")
        except Exception:
            check("WorkspacePermission invalid level rejected", PASS)

    except Exception as exc:
        check("Data models", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. WorkspaceStore — workspace CRUD
# ------------------------------------------------------------------

def test_workspace_store_workspace() -> None:
    print("\n== WorkspaceStore — Workspace CRUD ==")
    try:
        from claw.workspace.model import Workspace
        from claw.workspace.store import WorkspaceStore

        store = WorkspaceStore(":memory:")

        ws = Workspace(id="ws-1", name="Alpha", owner_agent_id="main")
        created = store.create_workspace(ws)
        assert created.id == "ws-1"
        check("WorkspaceStore.create_workspace", PASS)

        fetched = store.get_workspace("ws-1")
        assert fetched is not None and fetched.name == "Alpha"
        check("WorkspaceStore.get_workspace", PASS)

        missing = store.get_workspace("nonexistent")
        assert missing is None
        check("WorkspaceStore.get_workspace returns None for missing", PASS)

        # INSERT OR IGNORE — duplicate id is silently skipped
        duplicate = Workspace(id="ws-1", name="Beta", owner_agent_id="main")
        store.create_workspace(duplicate)
        still_alpha = store.get_workspace("ws-1")
        assert still_alpha and still_alpha.name == "Alpha"
        check("WorkspaceStore.create_workspace duplicate ignored", PASS)

        ws2 = Workspace(id="ws-2", name="Beta", owner_agent_id="agent2")
        store.create_workspace(ws2)
        all_ws = store.list_workspaces()
        assert len(all_ws) == 2
        check("WorkspaceStore.list_workspaces", PASS)

        store.close()

    except Exception as exc:
        check("WorkspaceStore workspace CRUD", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. WorkspaceStore — documents
# ------------------------------------------------------------------

def test_workspace_store_documents() -> None:
    print("\n== WorkspaceStore — Documents ==")
    try:
        from claw.workspace.model import Document
        from claw.workspace.store import WorkspaceStore

        store = WorkspaceStore(":memory:")

        doc = Document(workspace_id="ws-1", name="notes.md", body="Hello")
        result = store.upsert_document(doc)
        assert result.id and result.name == "notes.md"
        check("WorkspaceStore.upsert_document (create)", PASS)

        fetched = store.get_document(result.id)
        assert fetched and fetched.body == "Hello"
        check("WorkspaceStore.get_document", PASS)

        # Upsert by same name → update body
        updated = Document(workspace_id="ws-1", name="notes.md", body="Updated body")
        result2 = store.upsert_document(updated)
        assert result2.id == result.id  # same id preserved
        assert result2.body == "Updated body"
        check("WorkspaceStore.upsert_document (update same name)", PASS)

        doc2 = Document(workspace_id="ws-1", name="plan.md", body="Plan here")
        store.upsert_document(doc2)
        docs = store.list_documents("ws-1")
        assert len(docs) == 2
        check("WorkspaceStore.list_documents", PASS)

        empty = store.list_documents("ws-99")
        assert empty == []
        check("WorkspaceStore.list_documents empty workspace", PASS)

        store.close()

    except Exception as exc:
        check("WorkspaceStore documents", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. WorkspaceStore — tasks
# ------------------------------------------------------------------

def test_workspace_store_tasks() -> None:
    print("\n== WorkspaceStore — Tasks ==")
    try:
        from claw.workspace.model import Task
        from claw.workspace.store import WorkspaceStore

        store = WorkspaceStore(":memory:")

        t1 = Task(workspace_id="ws-1", title="Write tests", priority=10)
        t2 = Task(workspace_id="ws-1", title="Ship it", priority=5)
        store.create_task(t1)
        store.create_task(t2)
        check("WorkspaceStore.create_task", PASS)

        fetched = store.get_task(t1.id)
        assert fetched and fetched.title == "Write tests" and fetched.status == "open"
        check("WorkspaceStore.get_task", PASS)

        all_tasks = store.list_tasks("ws-1")
        assert len(all_tasks) == 2
        # Higher priority first
        assert all_tasks[0].priority >= all_tasks[1].priority
        check("WorkspaceStore.list_tasks ordered by priority", PASS)

        updated = store.update_task(t1.id, status="done")
        assert updated and updated.status == "done"
        check("WorkspaceStore.update_task status", PASS)

        open_tasks = store.list_tasks("ws-1", status="open")
        assert len(open_tasks) == 1 and open_tasks[0].id == t2.id
        check("WorkspaceStore.list_tasks status filter", PASS)

        done_tasks = store.list_tasks("ws-1", status="done")
        assert len(done_tasks) == 1 and done_tasks[0].id == t1.id
        check("WorkspaceStore.list_tasks done filter", PASS)

        not_found = store.update_task("bad-id", status="done")
        assert not_found is None
        check("WorkspaceStore.update_task returns None for missing", PASS)

        store.close()

    except Exception as exc:
        check("WorkspaceStore tasks", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. WorkspaceStore — assets and permissions
# ------------------------------------------------------------------

def test_workspace_store_assets_perms() -> None:
    print("\n== WorkspaceStore — Assets & Permissions ==")
    try:
        from claw.workspace.model import Asset, WorkspacePermission
        from claw.workspace.store import WorkspaceStore

        store = WorkspaceStore(":memory:")

        a = Asset(workspace_id="ws-1", name="logo.png", path="/tmp/logo.png", size_bytes=1024)
        store.create_asset(a)
        assets = store.list_assets("ws-1")
        assert len(assets) == 1 and assets[0].name == "logo.png"
        check("WorkspaceStore.create_asset / list_assets", PASS)

        empty_assets = store.list_assets("ws-99")
        assert empty_assets == []
        check("WorkspaceStore.list_assets empty", PASS)

        perm = WorkspacePermission(workspace_id="ws-1", agent_id="agent2", level="read")
        store.set_permission(perm)
        fetched = store.get_permission("ws-1", "agent2")
        assert fetched and fetched.level == "read"
        check("WorkspaceStore.set_permission / get_permission", PASS)

        # Upgrade to write
        store.set_permission(WorkspacePermission(workspace_id="ws-1", agent_id="agent2", level="write"))
        upgraded = store.get_permission("ws-1", "agent2")
        assert upgraded and upgraded.level == "write"
        check("WorkspaceStore.set_permission upsert", PASS)

        all_perms = store.list_permissions("ws-1")
        assert len(all_perms) == 1
        check("WorkspaceStore.list_permissions", PASS)

        no_perm = store.get_permission("ws-1", "unknown-agent")
        assert no_perm is None
        check("WorkspaceStore.get_permission returns None for missing", PASS)

        store.close()

    except Exception as exc:
        check("WorkspaceStore assets & permissions", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. WorkspaceManager — async interface
# ------------------------------------------------------------------

async def _test_workspace_manager_async() -> None:
    from claw.workspace.model import Document, Task, WorkspacePermission
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)

    assert manager.is_enabled()
    check("WorkspaceManager.is_enabled", PASS)

    ws = await manager.ensure_workspace("main", "Main Agent")
    assert ws.id == "main" and ws.name == "Main Agent"
    check("WorkspaceManager.ensure_workspace creates workspace", PASS)

    ws2 = await manager.ensure_workspace("main")
    assert ws2.id == "main"
    check("WorkspaceManager.ensure_workspace idempotent", PASS)

    all_ws = await manager.list_workspaces()
    assert len(all_ws) == 1
    check("WorkspaceManager.list_workspaces", PASS)

    # Tasks
    task = Task(workspace_id="main", title="Fix bug", priority=1)
    created = await manager.create_task(task)
    assert created.id == task.id
    check("WorkspaceManager.create_task", PASS)

    tasks = await manager.list_tasks("main")
    assert len(tasks) == 1
    check("WorkspaceManager.list_tasks", PASS)

    updated = await manager.update_task(task.id, status="done")
    assert updated and updated.status == "done"
    check("WorkspaceManager.update_task", PASS)

    # Documents
    doc = Document(workspace_id="main", name="README.md", body="# Hello")
    upserted = await manager.upsert_document(doc)
    assert upserted.name == "README.md"
    check("WorkspaceManager.upsert_document", PASS)

    fetched_doc = await manager.get_document(upserted.id)
    assert fetched_doc and fetched_doc.body == "# Hello"
    check("WorkspaceManager.get_document", PASS)

    docs = await manager.list_documents("main")
    assert len(docs) == 1
    check("WorkspaceManager.list_documents", PASS)

    manager.close()


def test_workspace_manager() -> None:
    print("\n== WorkspaceManager ==")
    try:
        asyncio.run(_test_workspace_manager_async())
    except Exception as exc:
        check("WorkspaceManager", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. WorkspaceManager — permissions
# ------------------------------------------------------------------

async def _test_permissions_async() -> None:
    from claw.workspace.model import Workspace, WorkspacePermission
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)

    ws = Workspace(id="ws-a", name="Alpha", owner_agent_id="agent-a")
    await manager.create_workspace(ws)

    # Owner always has full access
    assert await manager.can_read("ws-a", "agent-a") is True
    check("WorkspaceManager.can_read — owner", PASS)
    assert await manager.can_write("ws-a", "agent-a") is True
    check("WorkspaceManager.can_write — owner", PASS)

    # Unknown agent has no access
    assert await manager.can_read("ws-a", "agent-b") is False
    check("WorkspaceManager.can_read — no permission", PASS)
    assert await manager.can_write("ws-a", "agent-b") is False
    check("WorkspaceManager.can_write — no permission", PASS)

    # Grant read
    await manager.set_permission(WorkspacePermission(workspace_id="ws-a", agent_id="agent-b", level="read"))
    assert await manager.can_read("ws-a", "agent-b") is True
    assert await manager.can_write("ws-a", "agent-b") is False
    check("WorkspaceManager read-only permission enforced", PASS)

    # Upgrade to write
    await manager.set_permission(WorkspacePermission(workspace_id="ws-a", agent_id="agent-b", level="write"))
    assert await manager.can_read("ws-a", "agent-b") is True
    assert await manager.can_write("ws-a", "agent-b") is True
    check("WorkspaceManager write permission enforced", PASS)

    # None permission revokes access
    await manager.set_permission(WorkspacePermission(workspace_id="ws-a", agent_id="agent-b", level="none"))
    assert await manager.can_read("ws-a", "agent-b") is False
    assert await manager.can_write("ws-a", "agent-b") is False
    check("WorkspaceManager none permission revokes access", PASS)

    perms = await manager.list_permissions("ws-a")
    assert len(perms) == 1 and perms[0].level == "none"
    check("WorkspaceManager.list_permissions", PASS)

    manager.close()


def test_workspace_permissions() -> None:
    print("\n== WorkspaceManager Permissions ==")
    try:
        asyncio.run(_test_permissions_async())
    except Exception as exc:
        check("WorkspaceManager permissions", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. Workspace tools
# ------------------------------------------------------------------

async def _test_workspace_tools_async() -> None:
    import json
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.tools import (
        register_workspace_tools,
        is_workspace_tool,
        _make_create_task,
        _make_list_tasks,
        _make_update_task,
        _make_create_document,
        _make_list_documents,
        _make_get_document,
    )

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)

    assert is_workspace_tool("ws_create_task")
    assert is_workspace_tool("ws_list_tasks")
    assert is_workspace_tool("ws_update_task")
    assert is_workspace_tool("ws_create_document")
    assert is_workspace_tool("ws_list_documents")
    assert is_workspace_tool("ws_get_document")
    assert not is_workspace_tool("remember")
    assert not is_workspace_tool("ws_nonexistent")
    check("is_workspace_tool", PASS)

    # ws_create_task
    handler = _make_create_task(manager)
    result = json.loads(await handler({"_agent_id": "main", "title": "Fix tests", "priority": 5}))
    assert "id" in result and result["title"] == "Fix tests" and result["status"] == "open"
    check("ws_create_task handler", PASS)

    task_id = result["id"]

    # ws_create_task missing title
    err = json.loads(await handler({"_agent_id": "main", "title": ""}))
    assert "error" in err
    check("ws_create_task missing title returns error", PASS)

    # ws_list_tasks
    list_handler = _make_list_tasks(manager)
    all_tasks = json.loads(await list_handler({"_agent_id": "main"}))
    assert all_tasks["count"] == 1 and all_tasks["tasks"][0]["id"] == task_id
    check("ws_list_tasks handler", PASS)

    open_tasks = json.loads(await list_handler({"_agent_id": "main", "status": "open"}))
    assert open_tasks["count"] == 1
    check("ws_list_tasks status filter", PASS)

    # ws_update_task
    update_handler = _make_update_task(manager)
    updated = json.loads(await update_handler({"task_id": task_id, "status": "done"}))
    assert updated["status"] == "done"
    check("ws_update_task handler", PASS)

    not_found = json.loads(await update_handler({"task_id": "bad-id", "status": "done"}))
    assert "error" in not_found
    check("ws_update_task not found returns error", PASS)

    no_id = json.loads(await update_handler({"status": "done"}))
    assert "error" in no_id
    check("ws_update_task missing task_id returns error", PASS)

    # ws_create_document
    doc_handler = _make_create_document(manager)
    doc_result = json.loads(await doc_handler({
        "_agent_id": "main", "name": "README.md", "body": "# Hello", "content_type": "markdown"
    }))
    assert "id" in doc_result and doc_result["name"] == "README.md"
    check("ws_create_document handler", PASS)

    doc_id = doc_result["id"]

    # Upsert — same name updates content
    updated_doc = json.loads(await doc_handler({
        "_agent_id": "main", "name": "README.md", "body": "# Updated", "content_type": "markdown"
    }))
    assert updated_doc["id"] == doc_id
    check("ws_create_document upsert same name", PASS)

    # ws_create_document missing name
    err_doc = json.loads(await doc_handler({"_agent_id": "main", "name": "", "body": "x"}))
    assert "error" in err_doc
    check("ws_create_document missing name returns error", PASS)

    # ws_list_documents
    list_docs_handler = _make_list_documents(manager)
    docs_result = json.loads(await list_docs_handler({"_agent_id": "main"}))
    assert docs_result["count"] == 1
    check("ws_list_documents handler", PASS)

    # ws_get_document
    get_doc_handler = _make_get_document(manager)
    fetched = json.loads(await get_doc_handler({"doc_id": doc_id}))
    assert fetched["body"] == "# Updated" and fetched["name"] == "README.md"
    check("ws_get_document handler", PASS)

    not_found_doc = json.loads(await get_doc_handler({"doc_id": "bad-id"}))
    assert "error" in not_found_doc
    check("ws_get_document not found returns error", PASS)

    no_doc_id = json.loads(await get_doc_handler({}))
    assert "error" in no_doc_id
    check("ws_get_document missing doc_id returns error", PASS)

    manager.close()


def test_workspace_tools() -> None:
    print("\n== Workspace Tools ==")
    try:
        asyncio.run(_test_workspace_tools_async())
    except Exception as exc:
        check("Workspace tools", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. register_workspace_tools into ToolRegistry
# ------------------------------------------------------------------

def test_register_workspace_tools() -> None:
    print("\n== register_workspace_tools ==")
    try:
        from claw.tools.registry import ToolRegistry
        from claw.workspace.store import WorkspaceStore
        from claw.workspace.manager import WorkspaceManager
        from claw.workspace.tools import register_workspace_tools

        store = WorkspaceStore(":memory:")
        manager = WorkspaceManager(store)
        registry = ToolRegistry()

        register_workspace_tools(registry, manager)
        defs = registry.definitions()
        names = {d["name"] for d in defs}
        assert "ws_create_task" in names
        assert "ws_list_tasks" in names
        assert "ws_update_task" in names
        assert "ws_create_document" in names
        assert "ws_list_documents" in names
        assert "ws_get_document" in names
        check("register_workspace_tools registers all 6 tools", PASS)

        # Duplicate registration is silently ignored
        register_workspace_tools(registry, manager)
        assert len(registry.definitions()) == len(defs)
        check("register_workspace_tools duplicate safe", PASS)

        store.close()

    except Exception as exc:
        check("register_workspace_tools", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 11. ClawGateway workspace_manager init
# ------------------------------------------------------------------

def test_gateway_workspace_init() -> None:
    print("\n== ClawGateway workspace_manager ==")
    try:
        from claw.config.schema import ClawConfig, CredentialConfig, WorkspaceConfig
        from claw.gateway.server import build_app

        # Disabled (default)
        cfg = ClawConfig(
            credentials=[CredentialConfig(api_key="sk-test")],
        )
        _, gw = build_app(cfg)
        assert gw.workspace_manager is None
        check("ClawGateway.workspace_manager is None when disabled", PASS)

        # Enabled with :memory: db
        cfg_on = ClawConfig(
            credentials=[CredentialConfig(api_key="sk-test")],
            workspace=WorkspaceConfig(enabled=True, db_path=":memory:"),
        )
        _, gw_on = build_app(cfg_on)
        from claw.workspace.manager import WorkspaceManager
        assert isinstance(gw_on.workspace_manager, WorkspaceManager)
        assert gw_on.workspace_manager.is_enabled()
        check("ClawGateway.workspace_manager initialized when enabled", PASS)

        if gw_on.workspace_manager:
            gw_on.workspace_manager.close()

    except Exception as exc:
        check("ClawGateway workspace_manager init", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 12. CLI workspace subcommands exit when disabled
# ------------------------------------------------------------------

def test_cli_workspace_disabled() -> None:
    print("\n== CLI workspace subcommands (disabled) ==")
    try:
        python = str(ROOT / "venv" / "Scripts" / "python.exe")
        if not Path(python).exists():
            python = sys.executable

        for subcmd in ("create TestWS", "list", "share ws-1 --agent agent2 --perm read"):
            result = subprocess.run(
                [python, "-m", "claw", "workspace"] + subcmd.split(),
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            output = result.stdout + result.stderr
            disabled = "disabled" in output.lower() or result.returncode != 0
            check(f"CLI workspace {subcmd.split()[0]} exits when disabled", PASS if disabled else FAIL)

    except Exception as exc:
        check("CLI workspace disabled check", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("AINDY Phase 6 — Workspace as First-Class Object")
    print("=" * 60)

    test_workspace_config()
    test_data_models()
    test_workspace_store_workspace()
    test_workspace_store_documents()
    test_workspace_store_tasks()
    test_workspace_store_assets_perms()
    test_workspace_manager()
    test_workspace_permissions()
    test_workspace_tools()
    test_register_workspace_tools()
    test_gateway_workspace_init()
    test_cli_workspace_disabled()

    print("\n" + "=" * 60)
    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    print(f"Results: {n_pass} passed  {n_fail} failed  {n_skip} skipped")
    print("=" * 60)

    if n_fail:
        print("\nFailed checks:")
        for name, status, note in results:
            if status == FAIL:
                print(f"  FAIL  {name}" + (f": {note}" if note else ""))
        sys.exit(1)


if __name__ == "__main__":
    main()
