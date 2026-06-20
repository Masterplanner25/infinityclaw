"""Weave data models."""
from __future__ import annotations
import os
import uuid
from pathlib import Path
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
