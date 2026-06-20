"""Per-agent capability models — defines what each agent is allowed to do."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FilesystemPermission(BaseModel):
    read: bool = False
    write: bool = False
    delete: bool = False
    paths: list[str] = Field(default_factory=list)  # empty = workspace only


class HttpPermission(BaseModel):
    enabled: bool = True
    allowlist: list[str] = Field(default_factory=list)  # empty = any URL
    denylist: list[str] = Field(default_factory=list)


class ToolPermission(BaseModel):
    allow: list[str] = Field(default_factory=lambda: ["*"])  # ["*"] = all tools
    deny: list[str] = Field(default_factory=list)


class SkillPermission(BaseModel):
    allow: list[str] = Field(default_factory=lambda: ["*"])
    deny: list[str] = Field(default_factory=list)


class CapabilitySet(BaseModel):
    """Full capability declaration for one agent.

    Declare in claw.toml:
        [[agents.list]]
        id = "main"
        capabilities = { tool_use = { deny = ["write_file"] }, external_http = { enabled = true } }
    """

    filesystem: FilesystemPermission = Field(default_factory=FilesystemPermission)
    external_http: HttpPermission = Field(default_factory=HttpPermission)
    tool_use: ToolPermission = Field(default_factory=ToolPermission)
    skill_use: SkillPermission = Field(default_factory=SkillPermission)
