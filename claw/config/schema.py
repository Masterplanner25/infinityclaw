"""Claw configuration schema — all settings as validated Pydantic models."""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from claw.permissions.model import CapabilitySet


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 18789
    token: Optional[str] = None  # bearer token; None disables auth


class ModelConfig(BaseModel):
    primary: str = "claude-sonnet-4-6"
    fallbacks: list[str] = []
    max_tokens: int = 4096
    temperature: float = 0.7


class AgentConfig(BaseModel):
    id: str
    name: str = ""
    workspace: str = ""  # resolved at runtime; defaults to ~/.claw/agents/<id>/workspace
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent_dir: str = ""  # resolved to ~/.claw/agents/<id> if empty
    default: bool = False
    capabilities: Optional[CapabilitySet] = None
    cross_agent_memory: list[str] = Field(default_factory=list)  # agent IDs whose memories to also read

    @field_validator("name", mode="before")
    @classmethod
    def _default_name(cls, v, info):
        return v or info.data.get("id", "")


class AgentsDefaults(BaseModel):
    workspace: str = ""
    model: ModelConfig = Field(default_factory=ModelConfig)


class AgentsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    defaults: AgentsDefaults = Field(default_factory=AgentsDefaults)
    agents: list[AgentConfig] = Field(default_factory=list, alias="list")

    def get(self, agent_id: str) -> Optional[AgentConfig]:
        for a in self.agents:
            if a.id == agent_id:
                return a
        return None

    def default_agent(self) -> Optional[AgentConfig]:
        for a in self.agents:
            if a.default:
                return a
        return self.agents[0] if self.agents else None


class CredentialConfig(BaseModel):
    id: str = ""
    provider: Literal["anthropic", "openai"] = "anthropic"
    api_key: str
    model: str = ""
    base_url: Optional[str] = None
    priority: int = 0
    context_window: int = 200_000

    @field_validator("id", mode="before")
    @classmethod
    def _default_id(cls, v, info):
        if v:
            return v
        idx = id(info)  # temporary; loader assigns sequential ids
        return f"profile-{idx}"


class BindingMatch(BaseModel):
    channel: Optional[str] = None
    channel_id: Optional[str] = None
    account_id: Optional[str] = None
    peer_id: Optional[str] = None
    guild_id: Optional[str] = None
    team_id: Optional[str] = None
    roles: list[str] = []


class Binding(BaseModel):
    agent_id: str
    match: BindingMatch = Field(default_factory=BindingMatch)


class DmScopeEnum(str):
    MAIN = "main"
    PER_PEER = "per-peer"
    PER_CHANNEL_PEER = "per-channel-peer"
    PER_ACCOUNT_CHANNEL_PEER = "per-account-channel-peer"


class ResetConfig(BaseModel):
    enabled: bool = True
    hour: int = 4    # 4 AM local time
    minute: int = 0


class SessionConfig(BaseModel):
    dm_scope: str = "main"
    identity_links: dict[str, list[str]] = Field(default_factory=dict)
    reset: ResetConfig = Field(default_factory=ResetConfig)
    max_messages: int = 200          # prune threshold
    compaction_threshold: int = 40   # summarize when messages >= this
    compaction_keep_recent: int = 20 # keep this many messages after compaction


class WebChatConfig(BaseModel):
    enabled: bool = True
    static_dir: str = ""  # defaults to package static/


class ChannelsConfig(BaseModel):
    webchat: WebChatConfig = Field(default_factory=WebChatConfig)
    extra: dict[str, Any] = Field(default_factory=dict)


class SkillsConfig(BaseModel):
    extra_dirs: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)  # empty = allow all
    deny: list[str] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    enabled: bool = False
    backend: str = "sqlite"
    db_path: str = ""  # defaults to ~/.claw/memory.db


class KnowledgeConfig(BaseModel):
    enabled: bool = False
    db_path: str = ""    # defaults to ~/.claw/knowledge.db
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5


class WorkspaceConfig(BaseModel):
    enabled: bool = False
    db_path: str = ""    # defaults to ~/.claw/workspace.db


class AINDYConfig(BaseModel):
    enabled: bool = False
    url: str = "http://localhost:8000"
    api_key: str = ""           # aindy_* platform key or JWT bearer token
    emit_events: bool = True    # fire-and-forget sys.v1.event.emit on turn lifecycle
    memory_backend: str = "local"  # "local" | "aindy" | "aindy-fallback"
    user_id: str = "claw"       # MAS identity root for path namespacing
    mounted: bool = False       # True when Claw is registered inside the AINDY platform layer


class CoordinationConfig(BaseModel):
    enabled: bool = False  # register delegate_to_agent tool; enable agent handoff


class WeaveConfig(BaseModel):
    enabled: bool = False
    node_id: str = ""   # empty = auto-generate UUID on first start
    db_path: str = ""   # empty -> ~/.claw/weave.db
    sync: bool = False  # push-based workspace replication to registered peers
    knowledge_sync_interval: int = 0  # seconds between knowledge federation pulls; 0 = disabled


class CronJobConfig(BaseModel):
    id: str = ""
    agent_id: str = "main"
    prompt: str
    cron: str  # 5-part cron expression
    delivery: str = "announce"   # announce | webhook | none
    delivery_channel: str = ""
    delivery_peer: str = ""
    webhook_url: str = ""
    enabled: bool = True


class ClawConfig(BaseModel):
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    credentials: list[CredentialConfig] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)
    session: SessionConfig = Field(default_factory=SessionConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    aindy: AINDYConfig = Field(default_factory=AINDYConfig)
    coordination: CoordinationConfig = Field(default_factory=CoordinationConfig)
    weave: WeaveConfig = Field(default_factory=WeaveConfig)
    cron: list[CronJobConfig] = Field(default_factory=list)
    state_dir: str = "~/.claw"
    log_level: str = "info"
