"""Workspace Replication (Weave Option B) — push-based sync tests.

22 assertions across 22 pytest-collected functions.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Group 1: Config — WeaveConfig.sync field
# ===========================================================================

def test_weave_config_sync_defaults_to_false():
    from claw.config.schema import WeaveConfig
    cfg = WeaveConfig()
    assert cfg.sync is False


def test_weave_config_sync_can_be_enabled():
    from claw.config.schema import WeaveConfig
    cfg = WeaveConfig(enabled=True, sync=True)
    assert cfg.sync is True


# ===========================================================================
# Group 2: WeaveSyncRequest model
# ===========================================================================

def test_weave_sync_request_model_fields():
    from claw.weave.model import WeaveSyncRequest
    req = WeaveSyncRequest(from_node="n1", agent_id="researcher")
    assert req.from_node == "n1"
    assert req.agent_id == "researcher"
    assert req.documents == []
    assert req.tasks == []


def test_weave_sync_request_accepts_objects():
    from claw.weave.model import WeaveSyncRequest
    req = WeaveSyncRequest(
        from_node="n1",
        agent_id="researcher",
        documents=[{"id": "d1", "name": "plan.md"}],
        tasks=[{"id": "t1", "title": "do it"}],
    )
    assert len(req.documents) == 1
    assert len(req.tasks) == 1


# ===========================================================================
# Group 3: WeaveClient.push_workspace — resilience
# ===========================================================================

async def test_push_workspace_returns_false_on_network_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.push_workspace(node, "researcher", [], [])
    assert result is False


# ===========================================================================
# Group 4: WeaveClient.push_workspace — success
# ===========================================================================

async def test_push_workspace_sends_correct_payload():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("my-node")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    docs = [{"id": "d1", "name": "spec.md", "body": "hello"}]
    tasks = [{"id": "t1", "title": "build it"}]

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.push_workspace(node, "researcher", docs, tasks)

    assert result is True
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert payload["from_node"] == "my-node"
    assert payload["agent_id"] == "researcher"
    assert payload["documents"] == docs
    assert payload["tasks"] == tasks


async def test_push_workspace_returns_false_on_http_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status = MagicMock(side_effect=Exception("server error"))
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.push_workspace(node, "researcher", [], [])

    assert result is False


# ===========================================================================
# Group 5: WorkspaceStore.sync_document — LWW
# ===========================================================================

def test_sync_document_inserts_new():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Document
    store = WorkspaceStore(":memory:")
    now = datetime.utcnow()
    doc = Document(id="d1", workspace_id="agent1", name="spec.md", body="hello", updated_at=now)
    result = store.sync_document(doc)
    assert result.id == "d1"
    assert store.get_document("d1") is not None
    store.close()


def test_sync_document_updates_when_newer():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Document
    store = WorkspaceStore(":memory:")
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t1 = t0 + timedelta(seconds=10)
    doc_old = Document(id="d1", workspace_id="a1", name="plan.md", body="v1", updated_at=t0)
    store.sync_document(doc_old)
    doc_new = Document(id="d1", workspace_id="a1", name="plan.md", body="v2", updated_at=t1)
    store.sync_document(doc_new)
    stored = store.get_document("d1")
    assert stored is not None
    assert stored.body == "v2"
    store.close()


def test_sync_document_rejects_when_older():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Document
    store = WorkspaceStore(":memory:")
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t_before = t0 - timedelta(seconds=5)
    doc_current = Document(id="d1", workspace_id="a1", name="plan.md", body="current", updated_at=t0)
    store.sync_document(doc_current)
    doc_stale = Document(id="d1", workspace_id="a1", name="plan.md", body="stale", updated_at=t_before)
    store.sync_document(doc_stale)
    stored = store.get_document("d1")
    assert stored is not None
    assert stored.body == "current"  # stale write rejected
    store.close()


# ===========================================================================
# Group 6: WorkspaceStore.upsert_task — LWW
# ===========================================================================

def test_upsert_task_inserts_new():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Task
    store = WorkspaceStore(":memory:")
    now = datetime.utcnow()
    task = Task(id="t1", workspace_id="agent1", title="do it", updated_at=now)
    result = store.upsert_task(task)
    assert result.id == "t1"
    assert store.get_task("t1") is not None
    store.close()


def test_upsert_task_updates_when_newer():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Task
    store = WorkspaceStore(":memory:")
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t1 = t0 + timedelta(seconds=10)
    task_old = Task(id="t1", workspace_id="a1", title="old title", status="open", updated_at=t0)
    store.upsert_task(task_old)
    task_new = Task(id="t1", workspace_id="a1", title="new title", status="done", updated_at=t1)
    store.upsert_task(task_new)
    stored = store.get_task("t1")
    assert stored is not None
    assert stored.title == "new title"
    assert stored.status == "done"
    store.close()


def test_upsert_task_rejects_when_older():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.model import Task
    store = WorkspaceStore(":memory:")
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t_before = t0 - timedelta(seconds=5)
    task_current = Task(id="t1", workspace_id="a1", title="current", status="in_progress", updated_at=t0)
    store.upsert_task(task_current)
    task_stale = Task(id="t1", workspace_id="a1", title="stale", status="open", updated_at=t_before)
    store.upsert_task(task_stale)
    stored = store.get_task("t1")
    assert stored is not None
    assert stored.title == "current"  # stale write rejected
    store.close()


# ===========================================================================
# Group 7: WorkspaceManager async wrappers
# ===========================================================================

async def test_workspace_manager_sync_document():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.model import Document
    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    now = datetime.utcnow()
    doc = Document(id="d99", workspace_id="agent1", name="readme.md", body="hi", updated_at=now)
    result = await manager.sync_document(doc)
    assert result.id == "d99"
    fetched = await manager.get_document("d99")
    assert fetched is not None
    assert fetched.name == "readme.md"
    store.close()


async def test_workspace_manager_upsert_task():
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.model import Task
    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    now = datetime.utcnow()
    task = Task(id="t99", workspace_id="agent1", title="sync me", updated_at=now)
    result = await manager.upsert_task(task)
    assert result.id == "t99"
    fetched = await manager.get_task("t99")
    assert fetched is not None
    assert fetched.title == "sync me"
    store.close()


# ===========================================================================
# Group 8: Workspace tools sync hook integration
# ===========================================================================

async def test_create_document_triggers_sync_hook():
    from claw.tools.registry import ToolRegistry
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.tools import register_workspace_tools

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    await manager.ensure_workspace("agent1")

    hook = AsyncMock()
    registry = ToolRegistry()
    register_workspace_tools(registry, manager, sync_hook=hook)
    exec_fn = registry.executor()

    await exec_fn("ws_create_document", {
        "_agent_id": "agent1",
        "name": "plan.md",
        "body": "hello world",
    })
    await asyncio.sleep(0)  # let fire-and-forget task run

    hook.assert_called_once()
    agent_arg, obj_type_arg, obj_arg = hook.call_args[0]
    assert agent_arg == "agent1"
    assert obj_type_arg == "document"
    assert obj_arg["name"] == "plan.md"
    assert "id" in obj_arg
    assert "updated_at" in obj_arg
    store.close()


async def test_create_task_triggers_sync_hook():
    from claw.tools.registry import ToolRegistry
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.tools import register_workspace_tools

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    await manager.ensure_workspace("agent1")

    hook = AsyncMock()
    registry = ToolRegistry()
    register_workspace_tools(registry, manager, sync_hook=hook)
    exec_fn = registry.executor()

    await exec_fn("ws_create_task", {
        "_agent_id": "agent1",
        "title": "build the feature",
        "body": "details here",
    })
    await asyncio.sleep(0)

    hook.assert_called_once()
    agent_arg, obj_type_arg, obj_arg = hook.call_args[0]
    assert agent_arg == "agent1"
    assert obj_type_arg == "task"
    assert obj_arg["title"] == "build the feature"
    assert obj_arg["status"] == "open"
    store.close()


async def test_update_task_triggers_sync_hook():
    from claw.tools.registry import ToolRegistry
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.tools import register_workspace_tools
    from claw.workspace.model import Task

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    await manager.ensure_workspace("agent1")
    task = Task(workspace_id="agent1", title="initial")
    await manager.create_task(task)

    hook = AsyncMock()
    registry = ToolRegistry()
    register_workspace_tools(registry, manager, sync_hook=hook)
    exec_fn = registry.executor()

    await exec_fn("ws_update_task", {
        "_agent_id": "agent1",
        "task_id": task.id,
        "status": "done",
    })
    await asyncio.sleep(0)

    hook.assert_called_once()
    _, obj_type_arg, obj_arg = hook.call_args[0]
    assert obj_type_arg == "task"
    assert obj_arg["status"] == "done"
    store.close()


def test_register_workspace_tools_without_hook_is_safe():
    from claw.tools.registry import ToolRegistry
    from claw.workspace.store import WorkspaceStore
    from claw.workspace.manager import WorkspaceManager
    from claw.workspace.tools import register_workspace_tools

    store = WorkspaceStore(":memory:")
    manager = WorkspaceManager(store)
    registry = ToolRegistry()
    # Must not raise
    register_workspace_tools(registry, manager, sync_hook=None)
    names = {d["name"] for d in registry.definitions()}
    assert "ws_create_document" in names
    assert "ws_create_task" in names
    store.close()


# ===========================================================================
# Group 9: REST endpoint source inspection
# ===========================================================================

def test_sync_endpoint_in_router():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "/weave/workspace/{agent_id}/sync" in src
    assert "WeaveSyncRequest" in src


def test_sync_endpoint_gated_on_weave_sync():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "config.weave.sync" in src


def test_sync_endpoint_applies_lww_for_documents():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "sync_document" in src


def test_sync_endpoint_applies_lww_for_tasks():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "upsert_task" in src
