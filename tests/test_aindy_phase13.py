"""Phase 13 — Cross-node workspace federation tests.

28 assertions across 14 pytest-collected functions.
"""
from __future__ import annotations

import inspect
import json


# ===========================================================================
# Group 1: WeaveClient resilience for new methods
# ===========================================================================

async def test_fetch_documents_returns_empty_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.fetch_documents(node, "researcher")
    assert result == []


async def test_fetch_document_returns_none_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.fetch_document(node, "researcher", "doc-123")
    assert result is None


async def test_fetch_tasks_returns_empty_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.fetch_tasks(node, "researcher")
    assert result == []


# ===========================================================================
# Group 2: WeaveClient with mock HTTP responses
# ===========================================================================

async def test_fetch_documents_parses_response():
    from unittest.mock import AsyncMock, MagicMock, patch
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "documents": [{"id": "d1", "name": "spec.md", "body": "hello"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        docs = await client.fetch_documents(node, "researcher")

    assert len(docs) == 1
    assert docs[0]["name"] == "spec.md"


async def test_fetch_document_returns_none_on_404():
    from unittest.mock import AsyncMock, MagicMock, patch
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.fetch_document(node, "researcher", "missing")

    assert result is None


async def test_fetch_tasks_passes_status_param():
    from unittest.mock import AsyncMock, MagicMock, patch, call
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"tasks": [{"id": "t1", "title": "do it", "status": "open"}]}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        tasks = await client.fetch_tasks(node, "researcher", status="open")

    assert len(tasks) == 1
    # Verify the status param was passed
    call_kwargs = mock_client.get.call_args
    assert call_kwargs.kwargs.get("params") == {"status": "open"}


# ===========================================================================
# Group 3: is_weave_tool covers new tools
# ===========================================================================

def test_is_weave_tool_new_tools():
    from claw.weave.tools import is_weave_tool
    assert is_weave_tool("weave_list_workspace_documents") is True
    assert is_weave_tool("weave_read_document") is True
    assert is_weave_tool("weave_list_workspace_tasks") is True


# ===========================================================================
# Group 4: New tools registered by register_weave_tools
# ===========================================================================

def test_new_workspace_tools_registered():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local")
    register_weave_tools(registry, store, client)

    names = {d["name"] for d in registry.definitions()}
    assert "weave_list_workspace_documents" in names
    assert "weave_read_document" in names
    assert "weave_list_workspace_tasks" in names
    store.close()


def test_new_tool_schemas_have_required_fields():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local")
    register_weave_tools(registry, store, client)

    defs = {d["name"]: d for d in registry.definitions()}

    list_req = defs["weave_list_workspace_documents"]["input_schema"].get("required", [])
    assert "node_id" in list_req
    assert "agent_id" in list_req

    read_req = defs["weave_read_document"]["input_schema"].get("required", [])
    assert "node_id" in read_req
    assert "agent_id" in read_req
    assert "doc_id" in read_req

    task_req = defs["weave_list_workspace_tasks"]["input_schema"].get("required", [])
    assert "node_id" in task_req
    assert "agent_id" in task_req

    store.close()


# ===========================================================================
# Group 5: Tool handler behavior
# ===========================================================================

async def test_weave_list_workspace_documents_unknown_node():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local")
    register_weave_tools(registry, store, client)
    exec_fn = registry.executor()

    result = await exec_fn("weave_list_workspace_documents", {
        "node_id": "no-such-node", "agent_id": "researcher",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    store.close()


async def test_weave_read_document_unknown_node():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local")
    register_weave_tools(registry, store, client)
    exec_fn = registry.executor()

    result = await exec_fn("weave_read_document", {
        "node_id": "no-such-node", "agent_id": "researcher", "doc_id": "d1",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    store.close()


async def test_weave_read_document_doc_not_found():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://remote:8000"))

    class NullClient:
        local_node_id = "local"
        async def fetch_document(self, node, agent_id, doc_id):
            return None  # 404 / not found

    register_weave_tools(registry, store, NullClient())
    exec_fn = registry.executor()

    result = await exec_fn("weave_read_document", {
        "node_id": "n1", "agent_id": "researcher", "doc_id": "missing-doc",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    assert "missing-doc" in parsed["error"]
    store.close()


async def test_weave_list_workspace_documents_returns_list():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://remote:8000"))

    class MockClient:
        local_node_id = "local"
        async def fetch_documents(self, node, agent_id):
            return [{"id": "d1", "name": "plan.md", "body": "step 1"}]

    register_weave_tools(registry, store, MockClient())
    exec_fn = registry.executor()

    result = await exec_fn("weave_list_workspace_documents", {
        "node_id": "n1", "agent_id": "researcher",
    })
    parsed = json.loads(result)
    assert parsed["documents"][0]["name"] == "plan.md"
    store.close()


async def test_weave_list_workspace_tasks_passes_status():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://remote:8000"))

    captured = {}

    class MockClient:
        local_node_id = "local"
        async def fetch_tasks(self, node, agent_id, status=""):
            captured["status"] = status
            return [{"id": "t1", "title": "ship it", "status": status}]

    register_weave_tools(registry, store, MockClient())
    exec_fn = registry.executor()

    await exec_fn("weave_list_workspace_tasks", {
        "node_id": "n1", "agent_id": "researcher", "status": "open",
    })
    assert captured["status"] == "open"
    store.close()


# ===========================================================================
# Group 6: REST endpoint source inspection
# ===========================================================================

def test_workspace_federation_endpoints_in_router():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "/weave/workspace/{agent_id}/documents" in src
    assert "/weave/workspace/{agent_id}/documents/{doc_id}" in src
    assert "/weave/workspace/{agent_id}/tasks" in src


def test_workspace_endpoints_gated_on_workspace_enabled():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    # Endpoints are inside a workspace.enabled check
    assert "workspace.enabled" in src
    # model_dump is used to serialize Pydantic workspace objects
    assert "model_dump" in src
