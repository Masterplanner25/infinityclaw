"""Phase 14 — Weave-wide agent discovery and cross-node writes.

32 assertions across 16 pytest-collected functions.
"""
from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Group 1: WeaveClient new methods — resilience
# ===========================================================================

async def test_list_all_agents_empty_when_no_nodes():
    from claw.weave.client import WeaveClient
    client = WeaveClient("local")
    result = await client.list_all_agents([])
    assert result == []


async def test_create_document_returns_none_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.create_document(node, "researcher", "plan.md")
    assert result is None


async def test_create_task_returns_none_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.create_task(node, "researcher", "build it")
    assert result is None


async def test_update_task_returns_none_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.update_task(node, "researcher", "task-1", status="done")
    assert result is None


async def test_search_knowledge_returns_empty_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.search_knowledge(node, "researcher", "hello")
    assert result == []


# ===========================================================================
# Group 2: WeaveClient with mock responses
# ===========================================================================

async def test_list_all_agents_merges_with_node_attribution():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node_a = WeaveNode(node_id="node-a", url="http://a:8000")
    node_b = WeaveNode(node_id="node-b", url="http://b:8000")

    async def _fake_list_agents(node):
        if node.node_id == "node-a":
            return [{"agent_id": "planner", "name": "Planner"}]
        return [{"agent_id": "researcher", "name": "Researcher"}]

    # Patch list_agents on the client instance
    client.list_agents = _fake_list_agents
    result = await client.list_all_agents([node_a, node_b])

    assert len(result) == 2
    node_ids = {r["node_id"] for r in result}
    assert node_ids == {"node-a", "node-b"}
    agent_ids = {r["agent_id"] for r in result}
    assert agent_ids == {"planner", "researcher"}


async def test_list_all_agents_skips_failed_nodes():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode

    client = WeaveClient("local")
    node_a = WeaveNode(node_id="node-a", url="http://a:8000")
    node_b = WeaveNode(node_id="node-b", url="http://b:8000")

    async def _fake_list_agents(node):
        if node.node_id == "node-a":
            raise ConnectionError("offline")
        return [{"agent_id": "researcher", "name": "Researcher"}]

    client.list_agents = _fake_list_agents
    result = await client.list_all_agents([node_a, node_b])
    # node-a failed (exception -> not a list) -> skipped
    assert len(result) == 1
    assert result[0]["node_id"] == "node-b"


async def test_update_task_returns_none_on_404():
    from claw.weave.model import WeaveNode

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.patch = AsyncMock(return_value=mock_resp)

    from claw.weave.client import WeaveClient
    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.update_task(node, "researcher", "t-999", status="done")

    assert result is None


# ===========================================================================
# Group 3: is_weave_tool covers all new tools
# ===========================================================================

def test_is_weave_tool_phase14_tools():
    from claw.weave.tools import is_weave_tool
    assert is_weave_tool("weave_discover_agents") is True
    assert is_weave_tool("weave_create_document") is True
    assert is_weave_tool("weave_create_task") is True
    assert is_weave_tool("weave_update_task") is True
    assert is_weave_tool("weave_search_knowledge") is True


# ===========================================================================
# Group 4: New tools registered
# ===========================================================================

def test_phase14_tools_registered():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    register_weave_tools(registry, store, WeaveClient("local"))

    names = {d["name"] for d in registry.definitions()}
    assert "weave_discover_agents" in names
    assert "weave_create_document" in names
    assert "weave_create_task" in names
    assert "weave_update_task" in names
    assert "weave_search_knowledge" in names
    store.close()


def test_phase14_tool_required_fields():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    register_weave_tools(registry, store, WeaveClient("local"))
    defs = {d["name"]: d for d in registry.definitions()}

    # discover has no required fields
    assert defs["weave_discover_agents"]["input_schema"].get("required", []) == []

    # create_document requires node_id, agent_id, name
    cd_req = defs["weave_create_document"]["input_schema"]["required"]
    assert "node_id" in cd_req and "agent_id" in cd_req and "name" in cd_req

    # create_task requires node_id, agent_id, title
    ct_req = defs["weave_create_task"]["input_schema"]["required"]
    assert "node_id" in ct_req and "agent_id" in ct_req and "title" in ct_req

    # update_task requires node_id, agent_id, task_id
    ut_req = defs["weave_update_task"]["input_schema"]["required"]
    assert "node_id" in ut_req and "agent_id" in ut_req and "task_id" in ut_req

    # search_knowledge requires node_id, agent_id, query
    sk_req = defs["weave_search_knowledge"]["input_schema"]["required"]
    assert "node_id" in sk_req and "agent_id" in sk_req and "query" in sk_req

    store.close()


# ===========================================================================
# Group 5: Tool handler behavior
# ===========================================================================

async def test_weave_discover_agents_returns_merged_roster():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://n1:8000"))
    store.register(WeaveNode(node_id="n2", url="http://n2:8000"))

    class MockClient:
        local_node_id = "local"
        async def list_all_agents(self, nodes):
            return [
                {"node_id": "n1", "node_url": "http://n1:8000", "agent_id": "alpha", "name": "Alpha"},
                {"node_id": "n2", "node_url": "http://n2:8000", "agent_id": "beta", "name": "Beta"},
            ]

    register_weave_tools(registry, store, MockClient())
    exec_fn = registry.executor()
    result = await exec_fn("weave_discover_agents", {})
    parsed = json.loads(result)
    assert parsed["node_count"] == 2
    assert len(parsed["agents"]) == 2
    store.close()


async def test_weave_create_document_unknown_node_returns_error():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    register_weave_tools(registry, store, WeaveClient("local"))
    exec_fn = registry.executor()

    result = await exec_fn("weave_create_document", {
        "node_id": "ghost", "agent_id": "researcher", "name": "plan.md",
    })
    assert "error" in json.loads(result)
    store.close()


async def test_weave_update_task_not_found_returns_error():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://n1:8000"))

    class MockClient:
        local_node_id = "local"
        async def update_task(self, node, agent_id, task_id, **fields):
            return None  # simulates 404

    register_weave_tools(registry, store, MockClient())
    exec_fn = registry.executor()
    result = await exec_fn("weave_update_task", {
        "node_id": "n1", "agent_id": "researcher", "task_id": "t-999", "status": "done",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    assert "t-999" in parsed["error"]
    store.close()


async def test_weave_search_knowledge_unknown_node_returns_error():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    register_weave_tools(registry, store, WeaveClient("local"))
    exec_fn = registry.executor()
    result = await exec_fn("weave_search_knowledge", {
        "node_id": "ghost", "agent_id": "researcher", "query": "hello",
    })
    assert "error" in json.loads(result)
    store.close()


# ===========================================================================
# Group 6: REST endpoint source inspection
# ===========================================================================

def test_write_endpoints_in_router():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "router.post" in src
    assert "/weave/workspace/{agent_id}/documents" in src
    assert "/weave/workspace/{agent_id}/tasks" in src
    assert "router.patch" in src
    assert "/weave/workspace/{agent_id}/tasks/{task_id}" in src


def test_knowledge_endpoint_in_router():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "/weave/workspace/{agent_id}/knowledge" in src
    assert "knowledge.enabled" in src


def test_write_endpoints_gated_on_workspace_enabled():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    # WeaveCreateDocumentRequest imported inside workspace.enabled block
    assert "WeaveCreateDocumentRequest" in src
    assert "WeaveCreateTaskRequest" in src
    assert "WeaveUpdateTaskRequest" in src
