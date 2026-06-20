"""Phase 12 — Distributed Workspaces (Weave) tests.

38 assertions across 17 pytest-collected functions.
"""
from __future__ import annotations

import inspect
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Group 1: WeaveConfig and ClawConfig
# ===========================================================================

def test_weave_config_defaults():
    from claw.config.schema import WeaveConfig
    cfg = WeaveConfig()
    assert cfg.enabled is False
    assert cfg.node_id == ""
    assert cfg.db_path == ""


def test_claw_config_has_weave_field():
    from claw.config.schema import ClawConfig
    cfg = ClawConfig()
    assert hasattr(cfg, "weave")


def test_claw_config_weave_defaults_to_weave_config():
    from claw.config.schema import ClawConfig, WeaveConfig
    cfg = ClawConfig()
    assert isinstance(cfg.weave, WeaveConfig)
    assert cfg.weave.enabled is False


# ===========================================================================
# Group 2: WeaveNode model
# ===========================================================================

def test_weave_node_fields():
    from claw.weave.model import WeaveNode
    n = WeaveNode(node_id="n1", url="http://host:8000")
    assert n.node_id == "n1"
    assert n.url == "http://host:8000"
    assert n.label == ""
    assert n.api_key == ""


def test_weave_node_label_and_api_key():
    from claw.weave.model import WeaveNode
    n = WeaveNode(node_id="x", url="http://a", label="peer-A", api_key="secret")
    assert n.label == "peer-A"
    assert n.api_key == "secret"


# ===========================================================================
# Group 3: get_or_create_node_id
# ===========================================================================

def test_get_or_create_node_id_returns_config_value():
    from claw.weave.model import get_or_create_node_id
    result = get_or_create_node_id("fixed-id-123")
    assert result == "fixed-id-123"


def test_get_or_create_node_id_generates_uuid(tmp_path):
    from claw.weave.model import get_or_create_node_id
    result = get_or_create_node_id("", state_dir=str(tmp_path))
    # Must be a valid UUID
    uuid.UUID(result)
    assert len(result) == 36


def test_get_or_create_node_id_persists(tmp_path):
    from claw.weave.model import get_or_create_node_id
    first = get_or_create_node_id("", state_dir=str(tmp_path))
    second = get_or_create_node_id("", state_dir=str(tmp_path))
    assert first == second


# ===========================================================================
# Group 4: WeaveNodeStore
# ===========================================================================

def test_weave_node_store_register_and_get():
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode
    store = WeaveNodeStore(":memory:")
    node = WeaveNode(node_id="n1", url="http://host:9000", label="test")
    store.register(node)
    found = store.get("n1")
    assert found is not None
    assert found.node_id == "n1"
    assert found.url == "http://host:9000"
    assert found.label == "test"
    store.close()


def test_weave_node_store_list_nodes():
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="a", url="http://a"))
    store.register(WeaveNode(node_id="b", url="http://b"))
    nodes = store.list_nodes()
    assert len(nodes) == 2
    ids = {n.node_id for n in nodes}
    assert ids == {"a", "b"}
    store.close()


def test_weave_node_store_remove():
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://x"))
    removed = store.remove("n1")
    assert removed is True
    assert store.get("n1") is None
    store.close()


def test_weave_node_store_get_missing():
    from claw.weave.registry import WeaveNodeStore
    store = WeaveNodeStore(":memory:")
    assert store.get("nonexistent") is None
    store.close()


def test_weave_node_store_register_is_upsert():
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="n1", url="http://old"))
    store.register(WeaveNode(node_id="n1", url="http://new", label="updated"))
    found = store.get("n1")
    assert found.url == "http://new"
    assert found.label == "updated"
    assert len(store.list_nodes()) == 1
    store.close()


def test_weave_node_store_remove_returns_false_when_missing():
    from claw.weave.registry import WeaveNodeStore
    store = WeaveNodeStore(":memory:")
    assert store.remove("no-such-node") is False
    store.close()


# ===========================================================================
# Group 5: is_weave_tool
# ===========================================================================

def test_is_weave_tool_true_for_weave_tools():
    from claw.weave.tools import is_weave_tool
    assert is_weave_tool("weave_delegate") is True
    assert is_weave_tool("weave_list_nodes") is True
    assert is_weave_tool("weave_list_agents") is True


def test_is_weave_tool_false_for_non_weave():
    from claw.weave.tools import is_weave_tool
    assert is_weave_tool("remember") is False
    assert is_weave_tool("delegate_to_agent") is False
    assert is_weave_tool("ws_create_task") is False


# ===========================================================================
# Group 6: WeaveClient resilience
# ===========================================================================

async def test_weave_client_ping_returns_false_on_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local-node")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.ping(node)
    assert result is False


async def test_weave_client_delegate_returns_error_on_failure():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local-node")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.delegate(node, "agent1", "hello")
    assert result.startswith("[error:")


async def test_weave_client_list_agents_returns_empty_on_failure():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    client = WeaveClient("local-node")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    result = await client.list_agents(node)
    assert result == []


# ===========================================================================
# Group 7: register_weave_tools
# ===========================================================================

def test_register_weave_tools_registers_expected_tools():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local-node")
    register_weave_tools(registry, store, client)

    names = {d["name"] for d in registry.definitions()}
    assert "weave_delegate" in names
    assert "weave_list_nodes" in names
    assert "weave_list_agents" in names
    store.close()


def test_weave_delegate_schema_has_required_fields():
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    client = WeaveClient("local-node")
    register_weave_tools(registry, store, client)

    defs = {d["name"]: d for d in registry.definitions()}
    schema = defs["weave_delegate"]["input_schema"]
    required = schema.get("required", [])
    assert "node_id" in required
    assert "agent_id" in required
    assert "prompt" in required
    store.close()


# ===========================================================================
# Group 8: Gateway source inspection
# ===========================================================================

def test_gateway_has_weave_store_attribute():
    src = inspect.getsource(__import__("claw.gateway.server", fromlist=["ClawGateway"]).ClawGateway)
    assert "weave_store" in src


def test_gateway_has_weave_node_id_property():
    src = inspect.getsource(__import__("claw.gateway.server", fromlist=["ClawGateway"]).ClawGateway)
    assert "weave_node_id" in src


def test_startup_registers_weave_tools_when_enabled():
    src = inspect.getsource(__import__("claw.gateway.server", fromlist=["ClawGateway"]).ClawGateway.startup)
    assert "register_weave_tools" in src
    assert "weave.enabled" in src or "weave_store" in src


def test_scoped_executor_injects_for_weave_tools():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod)
    # Both scoped_executor and _inner_exec should check is_weave_tool
    assert src.count("is_weave_tool") >= 2


def test_build_claw_router_has_weave_endpoints():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "/weave/agents" in src
    assert "/weave/nodes" in src
    assert "/weave/nodes/register" in src
    assert "/weave/delegate" in src


# ===========================================================================
# Group 9: Weave delegate session key derivation
# ===========================================================================

async def test_weave_delegate_tool_derives_session_key():
    """weave_delegate handler must pass session key when _session_key is present."""
    from claw.tools.registry import ToolRegistry
    from claw.weave.tools import register_weave_tools
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.model import WeaveNode

    registry = ToolRegistry()
    store = WeaveNodeStore(":memory:")
    store.register(WeaveNode(node_id="remote-1", url="http://remote:8000"))

    captured_session = {}

    class MockClient:
        local_node_id = "local-node"
        async def delegate(self, node, agent_id, prompt, context="", session_key=""):
            captured_session["key"] = session_key
            return "ok"

    register_weave_tools(registry, store, MockClient())

    exec_fn = registry.executor()
    await exec_fn("weave_delegate", {
        "node_id": "remote-1",
        "agent_id": "researcher",
        "prompt": "summarize",
        "_session_key": "sess-abc",
    })
    assert "local-node" in captured_session["key"]
    assert "remote-1" in captured_session["key"]
    assert "researcher" in captured_session["key"]
    store.close()


def test_weave_delegate_endpoint_passes_session_key():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "session_key" in src
    assert "run_agent_turn" in src
