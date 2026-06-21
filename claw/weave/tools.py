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

_WEAVE_TOOLS = frozenset({
    "weave_delegate",
    "weave_list_nodes",
    "weave_list_agents",
    "weave_list_workspace_documents",
    "weave_read_document",
    "weave_list_workspace_tasks",
    "weave_discover_agents",
    "weave_create_document",
    "weave_create_task",
    "weave_update_task",
    "weave_search_knowledge",
})


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

    async def _weave_list_workspace_documents(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        docs = await client.fetch_documents(node, agent_id)
        return json.dumps({"node_id": node_id, "agent_id": agent_id, "documents": docs})

    registry.register(
        name="weave_list_workspace_documents",
        description=(
            "List documents in a remote agent's workspace on another Weave node. "
            "Returns document metadata (id, name, content_type) without body content; "
            "use weave_read_document to fetch the full body of a specific document."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace to read"},
            },
            "required": ["node_id", "agent_id"],
        },
        handler=_weave_list_workspace_documents,
    )

    async def _weave_read_document(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        doc_id = inp.get("doc_id", "")
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        doc = await client.fetch_document(node, agent_id, doc_id)
        if doc is None:
            return json.dumps({"error": f"document '{doc_id}' not found on node '{node_id}'"})
        return json.dumps(doc)

    registry.register(
        name="weave_read_document",
        description="Fetch the full content of a document from a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace contains the document"},
                "doc_id": {"type": "string", "description": "Document ID to fetch"},
            },
            "required": ["node_id", "agent_id", "doc_id"],
        },
        handler=_weave_read_document,
    )

    async def _weave_list_workspace_tasks(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        status = inp.get("status", "")
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        tasks = await client.fetch_tasks(node, agent_id, status)
        return json.dumps({"node_id": node_id, "agent_id": agent_id, "tasks": tasks})

    registry.register(
        name="weave_list_workspace_tasks",
        description="List tasks in a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace to read"},
                "status": {
                    "type": "string",
                    "description": "Optional status filter: open, in_progress, done, or cancelled",
                    "enum": ["open", "in_progress", "done", "cancelled"],
                },
            },
            "required": ["node_id", "agent_id"],
        },
        handler=_weave_list_workspace_tasks,
    )

    async def _weave_discover_agents(_inp: dict) -> str:
        nodes = store.list_nodes()
        agents = await client.list_all_agents(nodes)
        return json.dumps({"agents": agents, "node_count": len(nodes)})

    registry.register(
        name="weave_discover_agents",
        description=(
            "Query all registered Weave peer nodes concurrently and return a unified agent roster. "
            "Each entry includes node_id, node_url, agent_id, and name. "
            "Unreachable nodes are silently skipped."
        ),
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=_weave_discover_agents,
    )

    async def _weave_create_document(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        name = inp.get("name", "")
        body = inp.get("body", "")
        content_type = inp.get("content_type", "text")
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        doc = await client.create_document(node, agent_id, name, body, content_type)
        if doc is None:
            return json.dumps({"error": f"failed to create document on node '{node_id}'"})
        return json.dumps(doc)

    registry.register(
        name="weave_create_document",
        description="Create a document in a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace to write to"},
                "name": {"type": "string", "description": "Document name"},
                "body": {"type": "string", "description": "Document content"},
                "content_type": {"type": "string", "description": "Content type, e.g. text or markdown"},
            },
            "required": ["node_id", "agent_id", "name"],
        },
        handler=_weave_create_document,
    )

    async def _weave_create_task(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        title = inp.get("title", "")
        body = inp.get("body", "")
        priority = inp.get("priority", 0)
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        task = await client.create_task(node, agent_id, title, body, priority)
        if task is None:
            return json.dumps({"error": f"failed to create task on node '{node_id}'"})
        return json.dumps(task)

    registry.register(
        name="weave_create_task",
        description="Create a task in a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace to write to"},
                "title": {"type": "string", "description": "Task title"},
                "body": {"type": "string", "description": "Optional task description"},
                "priority": {"type": "integer", "description": "Priority (higher = more urgent)"},
            },
            "required": ["node_id", "agent_id", "title"],
        },
        handler=_weave_create_task,
    )

    async def _weave_update_task(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        task_id = inp.get("task_id", "")
        fields = {k: inp[k] for k in ("status", "title", "body", "priority") if k in inp}
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        task = await client.update_task(node, agent_id, task_id, **fields)
        if task is None:
            return json.dumps({"error": f"task '{task_id}' not found on node '{node_id}'"})
        return json.dumps(task)

    registry.register(
        name="weave_update_task",
        description="Update a task in a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose workspace owns the task"},
                "task_id": {"type": "string", "description": "ID of the task to update"},
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["open", "in_progress", "done", "cancelled"],
                },
                "title": {"type": "string", "description": "New title"},
                "body": {"type": "string", "description": "New description"},
                "priority": {"type": "integer", "description": "New priority"},
            },
            "required": ["node_id", "agent_id", "task_id"],
        },
        handler=_weave_update_task,
    )

    async def _weave_search_knowledge(inp: dict) -> str:
        node_id = inp.get("node_id", "")
        agent_id = inp.get("agent_id", "")
        query = inp.get("query", "")
        limit = inp.get("limit", 5)
        node = store.get(node_id)
        if node is None:
            return json.dumps({"error": f"unknown weave node '{node_id}'"})
        chunks = await client.search_knowledge(node, agent_id, query, limit)
        return json.dumps({"node_id": node_id, "agent_id": agent_id, "chunks": chunks})

    registry.register(
        name="weave_search_knowledge",
        description="Search the knowledge index of a remote agent's workspace on another Weave node.",
        input_schema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the remote Weave node"},
                "agent_id": {"type": "string", "description": "ID of the agent whose knowledge index to search"},
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Maximum number of results (default 5)"},
            },
            "required": ["node_id", "agent_id", "query"],
        },
        handler=_weave_search_knowledge,
    )
