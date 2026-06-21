"""Weave data models."""
from __future__ import annotations
import uuid
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class WeaveNode(BaseModel):
    node_id: str
    url: str
    label: str = ""
    api_key: str = ""


class WeaveDelegateRequest(BaseModel):
    from_node: str
    agent_id: str
    prompt: str
    context: str = ""
    session_key: str = ""


class WeaveRegisterRequest(BaseModel):
    node_id: str
    url: str
    label: str = ""
    api_key: str = ""


class WeaveCreateDocumentRequest(BaseModel):
    name: str
    body: str = ""
    content_type: str = "text"


class WeaveCreateTaskRequest(BaseModel):
    title: str
    body: str = ""
    priority: int = 0


class WeaveUpdateTaskRequest(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    priority: Optional[int] = None


class WeaveSyncRequest(BaseModel):
    from_node: str
    agent_id: str
    documents: list[dict] = []
    tasks: list[dict] = []


def get_or_create_node_id(config_node_id: str, state_dir: str = "") -> str:
    """Return config_node_id if set; otherwise read/create a persistent UUID on disk."""
    if config_node_id:
        return config_node_id
    if state_dir:
        id_path = Path(state_dir) / "node_id"
    else:
        id_path = Path.home() / ".claw" / "node_id"
    if id_path.exists():
        return id_path.read_text().strip()
    new_id = str(uuid.uuid4())
    id_path.parent.mkdir(parents=True, exist_ok=True)
    id_path.write_text(new_id)
    return new_id
