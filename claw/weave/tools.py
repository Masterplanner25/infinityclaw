"""Weave agent tools — cross-node delegation and discovery."""
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.gateway.tool_registry import ToolRegistry
    from claw.weave.registry import WeaveNodeStore
    from claw.weave.client import WeaveClient

logger = logging.getLogger(__name__)

_WEAVE_TOOLS = frozenset({"weave_delegate", "weave_list_nodes", "weave_list_agents"})


def is_weave_tool(name: str) -> bool:
    return name in _WEAVE_TOOLS


def register_weave_tools(
    registry: "ToolRegistry",
    store: "WeaveNodeStore",
    client: "WeaveClient",
) -> None:
    async def _weave_delegate(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        prompt = inp.get("prompt", "")
        context = inp.get("context", "")
        caller_session = inp.get("_session_key", "")
        from_node = client.local_node_id

        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})

        session_key = (
            f"weave:{from_node}:{caller_session}:{node_id}:{agent_id}"
            if caller_session else ""
        )
        return await client.delegate(node, agent_id, prompt, context, session_key)

    registry.register(
        name="weave_delegate",
        description=(
            "Delegate a prompt to an agent running on a remote Weave node. "
            "Use weave_list_nodes to discover reachable nodes and weave_list_agents to see "
            "which agents are available on a node."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the target agent on that node"},
                "prompt": {"type": "string", "description": "Prompt to send to the remote agent"},
                "context": {"type": "string", "description": "Optional extra context"},
            },
            "required": ["node_id", "agent_id", "prompt"],
        },
        handler=_weave_delegate,
    )

    async def _weave_list_nodes(_inp: dict) -> str:
        nodes = store.list_nodes()
        return json.dumps({
            "nodes": [
                {"node_id": n.node_id, "url": n.url, "label": n.label}
                for n in nodes
            ]
        })

    registry.register(
        name="weave_list_nodes",
        description="List all registered Weave peer nodes.",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=_weave_list_nodes,
    )

    async def _weave_list_agents(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        agents = await client.list_agents(node)
        return json.dumps({"node_id": node_id, "agents": agents})

    registry.register(
        name="weave_list_agents",
        description="List agents available on a remote Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
            },
            "required": ["node_id"],
        },
        handler=_weave_list_agents,
    )
