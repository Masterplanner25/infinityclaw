"""Workspace object tools registered into ToolRegistry for agent use.

Tool handlers receive agent_id dynamically via a '_agent_id' key injected
by the gateway's per-turn scoped executor — the LLM never sees this field.
Cross-workspace access: pass target_agent_id to operate on another agent's
workspace (requires an explicit permission grant via 'claw workspace share').
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw.tools.registry import ToolRegistry
    from claw.workspace.manager import WorkspaceManager

_WORKSPACE_TOOLS = {
    "ws_create_task",
    "ws_list_tasks",
    "ws_update_task",
    "ws_create_document",
    "ws_list_documents",
    "ws_get_document",
}


def register_workspace_tools(
    registry: "ToolRegistry",
    workspace_manager: "WorkspaceManager",
    sync_hook=None,
) -> None:
    """Register workspace object tools (once) into the shared registry.

    sync_hook: optional async callable(agent_id, obj_type, obj_dict) fired after
    successful writes for push-based Weave replication.
    """
    registry.register(
        name="ws_create_task",
        description=(
            "Create a new task in a workspace. Defaults to your own workspace; "
            "pass target_agent_id to create in another agent's workspace (requires "
            "write permission). Returns the task ID."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short task title.",
                },
                "body": {
                    "type": "string",
                    "description": "Optional details or description.",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority (higher = more urgent). Default 0.",
                    "default": 0,
                },
                "target_agent_id": {
                    "type": "string",
                    "description": "ID of another agent whose workspace to write to. Requires write permission.",
                },
            },
            "required": ["title"],
        },
        handler=_make_create_task(workspace_manager, sync_hook),
    )

    registry.register(
        name="ws_list_tasks",
        description=(
            "List tasks in a workspace. Defaults to your own workspace; pass "
            "target_agent_id to list another agent's tasks (requires read permission). "
            "Filter by status to see open, in_progress, done, or cancelled tasks."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done", "cancelled"],
                    "description": "Filter by status. Omit to see all tasks.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tasks to return. Default 20.",
                    "default": 20,
                },
                "target_agent_id": {
                    "type": "string",
                    "description": "ID of another agent whose workspace to read. Requires read permission.",
                },
            },
            "required": [],
        },
        handler=_make_list_tasks(workspace_manager),
    )

    registry.register(
        name="ws_update_task",
        description=(
            "Update a task's status, title, body, or priority by task ID. "
            "Cross-workspace: automatically enforces write permission if the task "
            "belongs to another agent's workspace."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done", "cancelled"],
                    "description": "New status.",
                },
                "title": {"type": "string", "description": "New title."},
                "body": {"type": "string", "description": "New body/details."},
                "priority": {"type": "integer", "description": "New priority."},
            },
            "required": ["task_id"],
        },
        handler=_make_update_task(workspace_manager, sync_hook),
    )

    registry.register(
        name="ws_create_document",
        description=(
            "Create or update a named document in a workspace. Defaults to your own "
            "workspace; pass target_agent_id to write to another agent's workspace "
            "(requires write permission). If a document with the same name already "
            "exists, its content is replaced. Returns the document ID."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Document name (unique in workspace).",
                },
                "body": {
                    "type": "string",
                    "description": "Document content.",
                },
                "content_type": {
                    "type": "string",
                    "enum": ["text", "markdown", "code", "json", "csv"],
                    "description": "Content type. Default: text.",
                    "default": "text",
                },
                "target_agent_id": {
                    "type": "string",
                    "description": "ID of another agent whose workspace to write to. Requires write permission.",
                },
            },
            "required": ["name", "body"],
        },
        handler=_make_create_document(workspace_manager, sync_hook),
    )

    registry.register(
        name="ws_list_documents",
        description=(
            "List documents in a workspace (most recently updated first). Defaults to "
            "your own workspace; pass target_agent_id to list another agent's documents "
            "(requires read permission)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max documents to return. Default 20.",
                    "default": 20,
                },
                "target_agent_id": {
                    "type": "string",
                    "description": "ID of another agent whose workspace to read. Requires read permission.",
                },
            },
            "required": [],
        },
        handler=_make_list_documents(workspace_manager),
    )

    registry.register(
        name="ws_get_document",
        description=(
            "Read the full content of a workspace document by its ID. "
            "Cross-workspace: automatically enforces read permission if the document "
            "belongs to another agent's workspace."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "The document ID (from ws_list_documents).",
                },
            },
            "required": ["doc_id"],
        },
        handler=_make_get_document(workspace_manager),
    )


def is_workspace_tool(name: str) -> bool:
    return name in _WORKSPACE_TOOLS


# ------------------------------------------------------------------
# Handler factories — agent_id comes from injected _agent_id key
# ------------------------------------------------------------------

def _make_create_task(manager: "WorkspaceManager", sync_hook=None):
    async def handler(input: dict) -> str:
        from claw.workspace.model import Task
        calling_agent = input.get("_agent_id", "main")
        target_agent = input.get("target_agent_id") or calling_agent
        title = input.get("title", "").strip()
        if not title:
            return json.dumps({"error": "title is required"})
        try:
            if target_agent != calling_agent:
                if not await manager.can_write(target_agent, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no write access to {target_agent}'s workspace"
                    })
            await manager.ensure_workspace(target_agent)
            task = Task(
                workspace_id=target_agent,
                title=title,
                body=input.get("body", ""),
                priority=int(input.get("priority", 0)),
            )
            task = await manager.create_task(task)
            if sync_hook is not None:
                asyncio.create_task(sync_hook(target_agent, "task", {
                    "id": task.id,
                    "workspace_id": task.workspace_id,
                    "title": task.title,
                    "body": task.body,
                    "status": task.status,
                    "priority": task.priority,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                }))
            return json.dumps({
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "workspace_id": task.workspace_id,
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_list_tasks(manager: "WorkspaceManager"):
    async def handler(input: dict) -> str:
        calling_agent = input.get("_agent_id", "main")
        target_agent = input.get("target_agent_id") or calling_agent
        status = input.get("status") or None
        limit = int(input.get("limit", 20))
        try:
            if target_agent != calling_agent:
                if not await manager.can_read(target_agent, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no read access to {target_agent}'s workspace"
                    })
            tasks = await manager.list_tasks(target_agent, status=status)
            tasks = tasks[:limit]
            return json.dumps({
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "priority": t.priority,
                        "body": t.body[:200],
                        "workspace_id": t.workspace_id,
                    }
                    for t in tasks
                ],
                "count": len(tasks),
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_update_task(manager: "WorkspaceManager", sync_hook=None):
    async def handler(input: dict) -> str:
        calling_agent = input.get("_agent_id", "main")
        task_id = input.get("task_id", "").strip()
        if not task_id:
            return json.dumps({"error": "task_id is required"})
        try:
            existing = await manager.get_task(task_id)
            if not existing:
                return json.dumps({"error": "task not found", "task_id": task_id})
            if existing.workspace_id != calling_agent:
                if not await manager.can_write(existing.workspace_id, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no write access to workspace {existing.workspace_id}"
                    })
            fields = {}
            for key in ("status", "title", "body", "priority"):
                if key in input and input[key] is not None:
                    fields[key] = input[key]
            task = await manager.update_task(task_id, **fields)
            if not task:
                return json.dumps({"error": "task not found", "task_id": task_id})
            if sync_hook is not None:
                asyncio.create_task(sync_hook(task.workspace_id, "task", {
                    "id": task.id,
                    "workspace_id": task.workspace_id,
                    "title": task.title,
                    "body": task.body,
                    "status": task.status,
                    "priority": task.priority,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                }))
            return json.dumps({"id": task.id, "title": task.title, "status": task.status})
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_create_document(manager: "WorkspaceManager", sync_hook=None):
    async def handler(input: dict) -> str:
        from claw.workspace.model import Document
        calling_agent = input.get("_agent_id", "main")
        target_agent = input.get("target_agent_id") or calling_agent
        name = input.get("name", "").strip()
        body = input.get("body", "")
        if not name:
            return json.dumps({"error": "name is required"})
        try:
            if target_agent != calling_agent:
                if not await manager.can_write(target_agent, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no write access to {target_agent}'s workspace"
                    })
            await manager.ensure_workspace(target_agent)
            now = datetime.utcnow()
            doc = Document(
                workspace_id=target_agent,
                name=name,
                body=body,
                content_type=input.get("content_type", "text"),
                updated_at=now,
            )
            doc = await manager.upsert_document(doc)
            if sync_hook is not None:
                asyncio.create_task(sync_hook(target_agent, "document", {
                    "id": doc.id,
                    "workspace_id": doc.workspace_id,
                    "name": doc.name,
                    "content_type": doc.content_type,
                    "body": doc.body,
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat(),
                }))
            return json.dumps({
                "id": doc.id,
                "name": doc.name,
                "content_type": doc.content_type,
                "workspace_id": doc.workspace_id,
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_list_documents(manager: "WorkspaceManager"):
    async def handler(input: dict) -> str:
        calling_agent = input.get("_agent_id", "main")
        target_agent = input.get("target_agent_id") or calling_agent
        limit = int(input.get("limit", 20))
        try:
            if target_agent != calling_agent:
                if not await manager.can_read(target_agent, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no read access to {target_agent}'s workspace"
                    })
            docs = await manager.list_documents(target_agent)
            docs = docs[:limit]
            return json.dumps({
                "documents": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "content_type": d.content_type,
                        "updated_at": d.updated_at.isoformat(),
                        "workspace_id": d.workspace_id,
                    }
                    for d in docs
                ],
                "count": len(docs),
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler


def _make_get_document(manager: "WorkspaceManager"):
    async def handler(input: dict) -> str:
        calling_agent = input.get("_agent_id", "main")
        doc_id = input.get("doc_id", "").strip()
        if not doc_id:
            return json.dumps({"error": "doc_id is required"})
        try:
            doc = await manager.get_document(doc_id)
            if not doc:
                return json.dumps({"error": "document not found", "doc_id": doc_id})
            if doc.workspace_id != calling_agent:
                if not await manager.can_read(doc.workspace_id, calling_agent):
                    return json.dumps({
                        "error": f"permission denied: no read access to workspace {doc.workspace_id}"
                    })
            return json.dumps({
                "id": doc.id,
                "name": doc.name,
                "content_type": doc.content_type,
                "body": doc.body,
                "updated_at": doc.updated_at.isoformat(),
                "workspace_id": doc.workspace_id,
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return handler
