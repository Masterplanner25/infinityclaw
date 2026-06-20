"""AgentRegistry — per-agent ConversationalTurn with isolated CredentialStores."""
from __future__ import annotations

import logging
from typing import Optional

from nodus_llm.profile import CredentialProfile, CredentialStore

from claw.config.schema import AgentConfig, ClawConfig, CredentialConfig
from .turn import ConversationalTurn
from .prompt import SystemPromptBuilder

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Owns one ConversationalTurn per agent.

    Each agent can optionally have its own credential set (per-agent isolation).
    If an agent has no credentials of its own, it falls back to the shared store.
    """

    def __init__(self, config: ClawConfig) -> None:
        self._config = config
        self._shared_store = _build_store(config.credentials)
        self._stores: dict[str, CredentialStore] = {}  # agent_id → store
        self._turns: dict[str, ConversationalTurn] = {}
        self._configs: dict[str, AgentConfig] = {}
        self._prompt_builder = SystemPromptBuilder()
        self._initialize()

    def _initialize(self) -> None:
        agents = self._config.agents.agents
        if not agents:
            from claw.config.schema import AgentConfig
            default = AgentConfig(id="main", name="Claw", default=True)
            agents = [default]

        for agent_cfg in agents:
            # Per-agent credential store: use shared store for now.
            # Individual agent credential overrides can be added via
            # agent_cfg.metadata["credentials"] in future phases.
            store = self._shared_store
            self._stores[agent_cfg.id] = store

            turn = ConversationalTurn(store)
            self._turns[agent_cfg.id] = turn
            self._configs[agent_cfg.id] = agent_cfg
            logger.info(
                "[registry] agent=%s model=%s ready",
                agent_cfg.id,
                agent_cfg.model.primary,
            )

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    def get_turn(self, agent_id: str) -> Optional[ConversationalTurn]:
        return self._turns.get(agent_id)

    def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        return self._configs.get(agent_id) or self._config.agents.get(agent_id)

    def get_credential_store(self, agent_id: str) -> Optional[CredentialStore]:
        return self._stores.get(agent_id)

    def get_prompt_builder(self) -> SystemPromptBuilder:
        return self._prompt_builder

    def agent_ids(self) -> list[str]:
        return list(self._turns.keys())

    def credential_store(self) -> CredentialStore:
        return self._shared_store

    # ------------------------------------------------------------------ #
    # Dynamic registration (for multi-agent CLI)
    # ------------------------------------------------------------------ #

    def register_agent(self, agent_cfg: AgentConfig, store: CredentialStore | None = None) -> None:
        """Dynamically add or replace an agent at runtime."""
        effective_store = store or self._shared_store
        self._stores[agent_cfg.id] = effective_store
        self._turns[agent_cfg.id] = ConversationalTurn(effective_store)
        self._configs[agent_cfg.id] = agent_cfg
        logger.info("[registry] registered agent=%s", agent_cfg.id)

    def unregister_agent(self, agent_id: str) -> bool:
        existed = agent_id in self._turns
        self._turns.pop(agent_id, None)
        self._stores.pop(agent_id, None)
        self._configs.pop(agent_id, None)
        return existed


def _build_store(cred_configs: list[CredentialConfig]) -> CredentialStore:
    profiles = []
    for c in cred_configs:
        model = c.model or ("claude-sonnet-4-6" if c.provider == "anthropic" else "gpt-4o")
        profiles.append(CredentialProfile(
            id=c.id,
            provider=c.provider,
            api_key=c.api_key,
            model=model,
            base_url=c.base_url,
            context_window=c.context_window,
            priority=c.priority,
        ))

    if not profiles:
        raise RuntimeError("No LLM credentials available")

    store = CredentialStore(profiles)
    logger.info("[registry] shared credential store: %d profile(s)", len(profiles))
    return store
