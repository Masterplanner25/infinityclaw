"""Workspace data models — Workspace, Document, Task, Asset, WorkspacePermission."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Workspace(BaseModel):
    id: str = Field(default_factory=_uid)
    name: str
    description: str = ""
    owner_agent_id: str
    created_at: datetime = Field(default_factory=_now)


class Document(BaseModel):
    id: str = Field(default_factory=_uid)
    workspace_id: str
    name: str
    content_type: str = "text"
    body: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Task(BaseModel):
    id: str = Field(default_factory=_uid)
    workspace_id: str
    title: str
    body: str = ""
    status: Literal["open", "in_progress", "done", "cancelled"] = "open"
    priority: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Asset(BaseModel):
    id: str = Field(default_factory=_uid)
    workspace_id: str
    name: str
    content_type: str = "binary"
    path: str = ""
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=_now)


class WorkspacePermission(BaseModel):
    workspace_id: str
    agent_id: str
    level: Literal["none", "read", "write"] = "read"
