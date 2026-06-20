"""AINDY Phase 9 milestone test -- Cross-Workspace Tool Access.

Tests (no real server or AINDY needed):
- ws_create_task in own workspace (baseline regression)
- ws_create_task in another agent's workspace with write permission
- ws_create_task in another agent's workspace without permission -- denied
- ws_create_task with read-only permission -- denied (write required)
- ws_list_tasks from another agent's workspace with read permission
- ws_list_tasks from another agent's workspace without permission -- denied
- ws_update_task on a cross-workspace task with write permission
- ws_update_task on a cross-workspace task without permission -- denied
- ws_create_document in another agent's workspace with write permission
- ws_create_document in another agent's workspace without permission -- denied
- ws_list_documents from another agent's workspace with read permission
- ws_list_documents from another agent's workspace without permission -- denied
- ws_get_document from another agent's workspace with read permission
- ws_get_document from another agent's workspace without permission -- denied
- Owner always has full access without explicit permission grant
- Read permission alone denies write operations
- Tool schemas include target_agent_id on applicable tools
- workspace_id included in create/list tool results

Run:  python tests/test_aindy_phase9.py
"""
from __future__ import annotations

import asyncio
import json
import os
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
# Fixtures
# ------------------------------------------------------------------

def _make_store_and_manager():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    return store, manager


def _make_tools(manager):
    from claw.workspace.tools import register_workspace_tools
    from claw.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_workspace_tools(registry, manager)
    return {d["name"]: d for d in registry.definitions()}


async def _call(tool_defs: dict, name: str, **kwargs) -> dict:
    """Find tool by name in the registry definitions and call its handler."""
    from claw.tools.registry import ToolRegistry
    from claw.workspace.tools import register_workspace_tools

    # Get handler from the stored handler map
    handler = tool_defs[name]["_handler"]
    result = await handler(kwargs)
    return json.loads(result)


def _setup_workspace_with_permission(manager, owner: str, grantee: str, level: str) -> None:
    """Create owner's workspace and grant grantee the given level."""
    from claw.workspace.model import WorkspacePermission

    asyncio.run(manager.ensure_workspace(owner))
    perm = WorkspacePermission(workspace_id=owner, agent_id=grantee, level=level)
    asyncio.run(manager.set_permission(perm))


# We need a way to call tool handlers directly. The registry stores handlers.
# Access them via a parallel dict.

def _build_handler_map(manager):
    """Build name -> handler mapping directly from tool factories."""
    from claw.workspace import tools as ws_tools

    return {
        "ws_create_task": ws_tools._make_create_task(manager),
        "ws_list_tasks": ws_tools._make_list_tasks(manager),
        "ws_update_task": ws_tools._make_update_task(manager),
        "ws_create_document": ws_tools._make_create_document(manager),
        "ws_list_documents": ws_tools._make_list_documents(manager),
        "ws_get_document": ws_tools._make_get_document(manager),
    }


# ------------------------------------------------------------------
# 1. Own-workspace regression (no cross-workspace)
# ------------------------------------------------------------------

def test_own_workspace_unaffected() -> None:
    print("\n== Own workspace baseline ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)

        # Create task in own workspace (no target_agent_id)
        result = asyncio.run(handlers["ws_create_task"]({"_agent_id": "alice", "title": "My task"}))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["workspace_id"] == "alice"
        check("ws_create_task in own workspace succeeds", PASS)

        # List tasks from own workspace
        result = asyncio.run(handlers["ws_list_tasks"]({"_agent_id": "alice"}))
        data = json.loads(result)
        assert data["count"] == 1
        assert data["tasks"][0]["workspace_id"] == "alice"
        check("ws_list_tasks returns own tasks with workspace_id", PASS)

        # Create document in own workspace
        result = asyncio.run(handlers["ws_create_document"](
            {"_agent_id": "alice", "name": "notes", "body": "hello"}
        ))
        data = json.loads(result)
        assert "error" not in data
        assert data["workspace_id"] == "alice"
        doc_id = data["id"]
        check("ws_create_document in own workspace succeeds", PASS)

        # Get document (own workspace — no cross-workspace check needed)
        result = asyncio.run(handlers["ws_get_document"]({"_agent_id": "alice", "doc_id": doc_id}))
        data = json.loads(result)
        assert "error" not in data
        assert data["workspace_id"] == "alice"
        check("ws_get_document from own workspace succeeds", PASS)

    except Exception as exc:
        check("own workspace regression", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Cross-workspace task operations
# ------------------------------------------------------------------

def test_cross_workspace_create_task_with_write_permission() -> None:
    print("\n== Cross-workspace ws_create_task (write permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="write")

        result = asyncio.run(handlers["ws_create_task"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "title": "Task from alice in bob's workspace",
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["workspace_id"] == "bob"
        check("ws_create_task in target workspace with write permission succeeds", PASS)
        assert "id" in data and "title" in data and "status" in data
        check("ws_create_task result includes id, title, status, workspace_id", PASS)

    except Exception as exc:
        check("cross-workspace create_task with write perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_create_task_denied() -> None:
    print("\n== Cross-workspace ws_create_task (no permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        result = asyncio.run(handlers["ws_create_task"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "title": "Unauthorized task",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_create_task without permission returns permission denied", PASS)

    except Exception as exc:
        check("cross-workspace create_task denied", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_create_task_read_only_denied() -> None:
    print("\n== Cross-workspace ws_create_task (read-only permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="read")

        result = asyncio.run(handlers["ws_create_task"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "title": "Read-only agent should not write",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_create_task with read-only permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace create_task read-only denied", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_list_tasks_with_read_permission() -> None:
    print("\n== Cross-workspace ws_list_tasks (read permission) ==")
    try:
        from claw.workspace.model import Task

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="read")

        # Seed a task in bob's workspace
        task = Task(workspace_id="bob", title="Bob's secret task")
        asyncio.run(manager.create_task(task))

        result = asyncio.run(handlers["ws_list_tasks"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["count"] == 1
        assert data["tasks"][0]["title"] == "Bob's secret task"
        assert data["tasks"][0]["workspace_id"] == "bob"
        check("ws_list_tasks from target workspace with read permission succeeds", PASS)

    except Exception as exc:
        check("cross-workspace list_tasks with read perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_list_tasks_denied() -> None:
    print("\n== Cross-workspace ws_list_tasks (no permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        result = asyncio.run(handlers["ws_list_tasks"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_list_tasks without permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace list_tasks denied", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_update_task_with_write_permission() -> None:
    print("\n== Cross-workspace ws_update_task (write permission) ==")
    try:
        from claw.workspace.model import Task

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="write")

        task = Task(workspace_id="bob", title="Bob's task", status="open")
        created = asyncio.run(manager.create_task(task))

        result = asyncio.run(handlers["ws_update_task"]({
            "_agent_id": "alice",
            "task_id": created.id,
            "status": "done",
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["status"] == "done"
        check("ws_update_task on cross-workspace task with write permission succeeds", PASS)

    except Exception as exc:
        check("cross-workspace update_task with write perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_update_task_denied() -> None:
    print("\n== Cross-workspace ws_update_task (no permission) ==")
    try:
        from claw.workspace.model import Task

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        task = Task(workspace_id="bob", title="Bob's task")
        created = asyncio.run(manager.create_task(task))

        result = asyncio.run(handlers["ws_update_task"]({
            "_agent_id": "alice",
            "task_id": created.id,
            "status": "done",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_update_task without permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace update_task denied", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. Cross-workspace document operations
# ------------------------------------------------------------------

def test_cross_workspace_create_document_with_write_permission() -> None:
    print("\n== Cross-workspace ws_create_document (write permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="write")

        result = asyncio.run(handlers["ws_create_document"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "name": "shared-notes",
            "body": "Notes from alice",
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["workspace_id"] == "bob"
        assert data["name"] == "shared-notes"
        check("ws_create_document in target workspace with write permission succeeds", PASS)
        assert "id" in data and "content_type" in data
        check("ws_create_document result includes id, name, content_type, workspace_id", PASS)

    except Exception as exc:
        check("cross-workspace create_document with write perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_create_document_denied() -> None:
    print("\n== Cross-workspace ws_create_document (no permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        result = asyncio.run(handlers["ws_create_document"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "name": "unauthorized",
            "body": "should fail",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_create_document without permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace create_document denied", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_list_documents_with_read_permission() -> None:
    print("\n== Cross-workspace ws_list_documents (read permission) ==")
    try:
        from claw.workspace.model import Document
        from datetime import datetime

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="read")

        doc = Document(workspace_id="bob", name="bob-doc", body="content", updated_at=datetime.utcnow())
        asyncio.run(manager.upsert_document(doc))

        result = asyncio.run(handlers["ws_list_documents"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["count"] == 1
        assert data["documents"][0]["name"] == "bob-doc"
        assert data["documents"][0]["workspace_id"] == "bob"
        check("ws_list_documents from target workspace with read permission succeeds", PASS)

    except Exception as exc:
        check("cross-workspace list_documents with read perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_list_documents_denied() -> None:
    print("\n== Cross-workspace ws_list_documents (no permission) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        result = asyncio.run(handlers["ws_list_documents"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_list_documents without permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace list_documents denied", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_get_document_with_read_permission() -> None:
    print("\n== Cross-workspace ws_get_document (read permission) ==")
    try:
        from claw.workspace.model import Document
        from datetime import datetime

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="read")

        doc = Document(workspace_id="bob", name="bob-secret", body="the content", updated_at=datetime.utcnow())
        saved = asyncio.run(manager.upsert_document(doc))

        result = asyncio.run(handlers["ws_get_document"]({
            "_agent_id": "alice",
            "doc_id": saved.id,
        }))
        data = json.loads(result)
        assert "error" not in data, f"unexpected error: {data}"
        assert data["body"] == "the content"
        assert data["workspace_id"] == "bob"
        check("ws_get_document from target workspace with read permission succeeds", PASS)

    except Exception as exc:
        check("cross-workspace get_document with read perm", FAIL, str(exc))
        traceback.print_exc()


def test_cross_workspace_get_document_denied() -> None:
    print("\n== Cross-workspace ws_get_document (no permission) ==")
    try:
        from claw.workspace.model import Document
        from datetime import datetime

        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        asyncio.run(manager.ensure_workspace("bob"))

        doc = Document(workspace_id="bob", name="private", body="secret", updated_at=datetime.utcnow())
        saved = asyncio.run(manager.upsert_document(doc))

        result = asyncio.run(handlers["ws_get_document"]({
            "_agent_id": "alice",
            "doc_id": saved.id,
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_get_document without permission returns denied", PASS)

    except Exception as exc:
        check("cross-workspace get_document denied", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. Owner always has full access
# ------------------------------------------------------------------

def test_owner_has_full_access_without_explicit_permission() -> None:
    print("\n== Owner access (no explicit permission needed) ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        # bob creates his own workspace — no explicit permission needed
        asyncio.run(manager.ensure_workspace("bob"))

        # bob creates a task in his own workspace
        result = asyncio.run(handlers["ws_create_task"]({
            "_agent_id": "bob",
            "title": "Owner task",
        }))
        data = json.loads(result)
        assert "error" not in data
        assert data["workspace_id"] == "bob"
        check("workspace owner creates task without explicit permission", PASS)

        # bob lists his own tasks
        result = asyncio.run(handlers["ws_list_tasks"]({"_agent_id": "bob"}))
        data = json.loads(result)
        assert data["count"] == 1
        check("workspace owner lists own tasks without explicit permission", PASS)

    except Exception as exc:
        check("owner full access", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. Read permission does not grant write
# ------------------------------------------------------------------

def test_read_permission_does_not_allow_write() -> None:
    print("\n== Read-only permission denies writes ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)
        _setup_workspace_with_permission(manager, owner="bob", grantee="alice", level="read")

        # alice has read; try to create doc (write op) — should fail
        result = asyncio.run(handlers["ws_create_document"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
            "name": "unauthorized-doc",
            "body": "should be denied",
        }))
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        check("ws_create_document with read-only permission returns denied", PASS)

        # alice CAN read documents with read permission
        result = asyncio.run(handlers["ws_list_documents"]({
            "_agent_id": "alice",
            "target_agent_id": "bob",
        }))
        data = json.loads(result)
        assert "error" not in data
        check("ws_list_documents with read-only permission succeeds", PASS)

    except Exception as exc:
        check("read-only permission denies write", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. Tool schema verification
# ------------------------------------------------------------------

def test_tool_schemas_include_target_agent_id() -> None:
    print("\n== Tool schema: target_agent_id present ==")
    try:
        from claw.workspace.tools import register_workspace_tools
        from claw.tools.registry import ToolRegistry
        from claw.workspace.store import WorkspaceStore
        from claw.workspace.manager import WorkspaceManager

        store = WorkspaceStore(":memory:")
        manager = WorkspaceManager(store)
        registry = ToolRegistry()
        register_workspace_tools(registry, manager)

        defs = {d["name"]: d for d in registry.definitions()}

        tools_with_target = ["ws_create_task", "ws_list_tasks", "ws_create_document", "ws_list_documents"]
        for name in tools_with_target:
            schema = defs[name]["input_schema"]
            assert "target_agent_id" in schema["properties"], \
                f"{name} missing target_agent_id in schema"
        check("ws_create_task, ws_list_tasks, ws_create_document, ws_list_documents have target_agent_id", PASS)

        # ID-based tools (ws_get_document, ws_update_task) do NOT need target_agent_id
        # because they infer workspace from the object ID
        for name in ("ws_get_document", "ws_update_task"):
            schema = defs[name]["input_schema"]
            assert "target_agent_id" not in schema.get("properties", {}), \
                f"{name} should NOT have target_agent_id (implicit from ID lookup)"
        check("ws_get_document and ws_update_task do not expose target_agent_id (implicit)", PASS)

    except Exception as exc:
        check("tool schema target_agent_id", FAIL, str(exc))
        traceback.print_exc()


def test_workspace_id_in_results() -> None:
    print("\n== workspace_id present in tool results ==")
    try:
        _, manager = _make_store_and_manager()
        handlers = _build_handler_map(manager)

        # create_task result
        result = asyncio.run(handlers["ws_create_task"]({"_agent_id": "main", "title": "t"}))
        data = json.loads(result)
        assert "workspace_id" in data, "ws_create_task result missing workspace_id"
        check("ws_create_task result includes workspace_id", PASS)

        # list_tasks result
        result = asyncio.run(handlers["ws_list_tasks"]({"_agent_id": "main"}))
        data = json.loads(result)
        assert data["count"] > 0
        assert "workspace_id" in data["tasks"][0], "task in ws_list_tasks missing workspace_id"
        check("ws_list_tasks task entries include workspace_id", PASS)

        # create_document result
        result = asyncio.run(handlers["ws_create_document"](
            {"_agent_id": "main", "name": "doc", "body": "b"}
        ))
        data = json.loads(result)
        assert "workspace_id" in data, "ws_create_document result missing workspace_id"
        check("ws_create_document result includes workspace_id", PASS)

        # list_documents result
        result = asyncio.run(handlers["ws_list_documents"]({"_agent_id": "main"}))
        data = json.loads(result)
        assert data["count"] > 0
        assert "workspace_id" in data["documents"][0], "doc in ws_list_documents missing workspace_id"
        check("ws_list_documents document entries include workspace_id", PASS)

        # get_document result
        doc_id = data["documents"][0]["id"]
        result = asyncio.run(handlers["ws_get_document"]({"_agent_id": "main", "doc_id": doc_id}))
        data = json.loads(result)
        assert "workspace_id" in data, "ws_get_document result missing workspace_id"
        check("ws_get_document result includes workspace_id", PASS)

    except Exception as exc:
        check("workspace_id in results", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    test_own_workspace_unaffected()
    test_cross_workspace_create_task_with_write_permission()
    test_cross_workspace_create_task_denied()
    test_cross_workspace_create_task_read_only_denied()
    test_cross_workspace_list_tasks_with_read_permission()
    test_cross_workspace_list_tasks_denied()
    test_cross_workspace_update_task_with_write_permission()
    test_cross_workspace_update_task_denied()
    test_cross_workspace_create_document_with_write_permission()
    test_cross_workspace_create_document_denied()
    test_cross_workspace_list_documents_with_read_permission()
    test_cross_workspace_list_documents_denied()
    test_cross_workspace_get_document_with_read_permission()
    test_cross_workspace_get_document_denied()
    test_owner_has_full_access_without_explicit_permission()
    test_read_permission_does_not_allow_write()
    test_tool_schemas_include_target_agent_id()
    test_workspace_id_in_results()

    print()
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _ in results if s == SKIP)
    total = len(results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
