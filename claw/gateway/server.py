"""ClawGateway — FastAPI app wiring all subsystems together."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from nodus_adapter_base import BaseChannelAdapter

from claw.agents.registry import AgentRegistry
from claw.agents.prompt import PromptContext
from claw.channels.pairing import PairingStore
from claw.channels.policy import DmPolicy, DmPolicyEnforcer
from claw.channels.registry import ChannelAdapterRegistry
from claw.config.schema import ClawConfig
from claw.routing.envelope import InboundEnvelope
from claw.routing.resolver import BindingResolver
from claw.sessions.key import SessionKeyBuilder
from claw.sessions.manager import ClawSessionManager
from claw.skills.gating import SkillGate
from claw.skills.injector import SkillsInjector
from claw.skills.loader import SkillLoader
from claw.auth.manager import AuthManager
from claw.memory.manager import MemoryManager
from claw.memory.injector import MemoryInjector
from claw.memory.tools import register_memory_tools
from claw.tools.registry import ToolRegistry
from claw.tools.standard import register_standard_tools
from claw.workspace.bootstrapper import WorkspaceBootstrapper
from claw.workspace.initializer import WorkspaceInitializer
from claw.workspace.store import WorkspaceStore
from claw.workspace.manager import WorkspaceManager
from claw.knowledge.index import KnowledgeIndex
from claw.knowledge.retrieval import KnowledgeRetriever
from claw.knowledge.injector import KnowledgeInjector
from claw_webchat.adapter import WebChatAdapter
from .auth import GatewayAuth

logger = logging.getLogger(__name__)


class ClawGateway:
    """Assembles and owns all Claw subsystems."""

    def __init__(self, config: ClawConfig) -> None:
        self.config = config
        self._state_dir = Path(config.state_dir).expanduser()

        # Core subsystems
        self.agent_registry = AgentRegistry(config)
        self.session_manager = ClawSessionManager(config.session)
        self.channel_registry = ChannelAdapterRegistry()
        self.auth_manager = AuthManager(config.gateway, state_dir=config.state_dir)
        self.auth = GatewayAuth(
            config.gateway.token,
            auth_manager=self.auth_manager,
            bypass=config.aindy.mounted,  # AINDY platform layer handles auth when mounted
        )
        self.pairing_store = PairingStore()
        self.dm_policy = DmPolicyEnforcer()  # open by default; tighten via config

        # Routing
        fallback = (config.agents.default_agent() or
                    (config.agents.agents[0] if config.agents.agents else None))
        fallback_id = fallback.id if fallback else "main"
        self.resolver = BindingResolver(config.bindings, fallback_agent_id=fallback_id)
        self.session_key_builder = SessionKeyBuilder(config.session)

        # Workspace
        self.workspace_bootstrapper = WorkspaceBootstrapper(config.state_dir)
        self.workspace_initializer = WorkspaceInitializer(config.state_dir)

        # Skills
        self.skill_loader = SkillLoader(
            state_dir=config.state_dir,
            extra_dirs=config.skills.extra_dirs,
        )
        self.skill_gate = SkillGate(allow=config.skills.allow, deny=config.skills.deny)
        self.skills_injector = SkillsInjector()

        # AINDY client (optional; None when disabled or aindy_sdk not installed)
        # Initialised before MemoryManager so it can be passed to the memory backend.
        self._aindy: Optional["_AsyncAINDYClient"] = None
        if config.aindy.enabled and config.aindy.api_key:
            try:
                from claw.aindy.client import _AsyncAINDYClient
                self._aindy = _AsyncAINDYClient(config.aindy.url, config.aindy.api_key)
                logger.info("[gateway] AINDY client initialized url=%s", config.aindy.url)
            except Exception as exc:
                logger.warning("[gateway] AINDY client init failed: %s", exc)

        # Memory
        self.memory_manager = MemoryManager(
            config.memory,
            state_dir=config.state_dir,
            aindy_client=self._aindy,
            aindy_memory_backend=config.aindy.memory_backend,
            aindy_user_id=config.aindy.user_id,
        )
        self.memory_injector = MemoryInjector()

        # Knowledge index (optional; None when disabled)
        if config.knowledge.enabled:
            _knowledge_db = (
                config.knowledge.db_path
                or str(self._state_dir / "knowledge.db")
            )
            self.knowledge_index: Optional[KnowledgeIndex] = KnowledgeIndex(_knowledge_db)
            self.knowledge_retriever: Optional[KnowledgeRetriever] = KnowledgeRetriever(
                self.knowledge_index, top_k=config.knowledge.top_k
            )
            self.knowledge_injector: Optional[KnowledgeInjector] = KnowledgeInjector()
        else:
            self.knowledge_index = None
            self.knowledge_retriever = None
            self.knowledge_injector = None

        # Workspace object store (optional; None when disabled)
        if config.workspace.enabled:
            _workspace_db = (
                config.workspace.db_path
                or str(self._state_dir / "workspace.db")
            )
            self.workspace_manager: Optional[WorkspaceManager] = WorkspaceManager(
                WorkspaceStore(_workspace_db)
            )
        else:
            self.workspace_manager = None

        # WebChat (always registered)
        self.webchat_adapter = WebChatAdapter()
        self.channel_registry.register(self.webchat_adapter)

        # Tool registry (shared across agents; per-agent isolation in Phase 4.9)
        self.tool_registry = ToolRegistry()

        # Cron scheduler (set in startup if cron jobs configured)
        self.cron_manager: Optional["CronManager"] = None

        # Background listener tasks for non-WebChat adapters
        self._listener_tasks: dict[str, asyncio.Task] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Initialize all agents, workspaces, channels, and background tasks."""
        if self._initialized:
            return

        agents = self.config.agents.agents or []
        if not agents:
            from claw.config.schema import AgentConfig
            agents = [AgentConfig(id="main", name="Claw", default=True)]

        for agent_cfg in agents:
            ws_dir = self.workspace_initializer.initialize(agent_cfg.id)
            logger.info("[gateway] agent=%s workspace=%s", agent_cfg.id, ws_dir)

        # Knowledge startup scan — index workspace files for each agent
        if self.knowledge_index is not None:
            from claw.knowledge.scanner import WorkspaceScanner
            from claw.knowledge.ingestion import ingest_file
            scanner = WorkspaceScanner()
            for agent_cfg in agents:
                ws_dir = self._state_dir / "agents" / agent_cfg.id / "workspace"
                files = scanner.scan(ws_dir)
                total = 0
                for path in files:
                    chunks = ingest_file(
                        path,
                        workspace_id=agent_cfg.id,
                        chunk_size=self.config.knowledge.chunk_size,
                        chunk_overlap=self.config.knowledge.chunk_overlap,
                    )
                    if chunks:
                        self.knowledge_index.clear_source(str(path), agent_cfg.id)
                        self.knowledge_index.upsert_many(chunks)
                        total += len(chunks)
                logger.info(
                    "[knowledge] indexed agent=%s files=%d chunks=%d",
                    agent_cfg.id, len(files), total,
                )

        # Standard tools
        default_agent = agents[0] if agents else None
        ws_path = str(
            self._state_dir / "agents" /
            (default_agent.id if default_agent else "main") /
            "workspace"
        )
        register_standard_tools(
            self.tool_registry,
            workspace_dir=ws_path,
            session_manager=self.session_manager,
        )

        # Memory tools — registered once; agent_id injected per turn by scoped executor
        if self.memory_manager.is_enabled():
            register_memory_tools(self.tool_registry, self.memory_manager)
            logger.info("[gateway] memory tools registered")

        # Workspace tools — registered once; agent_id injected per turn by scoped executor
        if self.workspace_manager is not None:
            from claw.workspace.tools import register_workspace_tools
            for agent_cfg in agents:
                await self.workspace_manager.ensure_workspace(agent_cfg.id, agent_cfg.name)
            register_workspace_tools(self.tool_registry, self.workspace_manager)
            logger.info("[gateway] workspace object tools registered")

        await self.channel_registry.connect_all()

        # Start listener tasks for all non-WebChat adapters
        for adapter in self.channel_registry.all():
            if not isinstance(adapter, WebChatAdapter):
                self._start_listener(adapter)

        # Cron manager
        try:
            from claw.cron.manager import CronManager
            self.cron_manager = CronManager(self)
            await self.cron_manager.startup()
        except ImportError:
            pass  # cron module not yet available

        self._initialized = True
        logger.info(
            "[gateway] startup complete — %d agent(s), %d channel(s), %d listener(s)",
            len(agents),
            len(self.channel_registry.all()),
            len(self._listener_tasks),
        )

    async def shutdown(self) -> None:
        # Cancel listener tasks
        for task in self._listener_tasks.values():
            task.cancel()
        if self._listener_tasks:
            await asyncio.gather(*self._listener_tasks.values(), return_exceptions=True)
        self._listener_tasks.clear()

        if self.cron_manager:
            await self.cron_manager.shutdown()

        await self.channel_registry.disconnect_all()

    def register_adapter(self, adapter: BaseChannelAdapter) -> None:
        """Register a channel adapter and start its listener (if already started)."""
        self.channel_registry.register(adapter)
        if self._initialized and not isinstance(adapter, WebChatAdapter):
            self._start_listener(adapter)

    # ------------------------------------------------------------------
    # Adapter listener loop
    # ------------------------------------------------------------------

    def _start_listener(self, adapter: BaseChannelAdapter) -> None:
        """Start a background task that routes messages from *adapter* to agents."""
        task = asyncio.create_task(
            self._listener_loop(adapter),
            name=f"listener:{adapter.channel_id}",
        )
        self._listener_tasks[adapter.channel_id] = task
        logger.info("[gateway] listener started channel=%s", adapter.channel_id)

    async def _listener_loop(self, adapter: BaseChannelAdapter) -> None:
        """Subscribe to *adapter* and dispatch each message to handle_inbound."""
        try:
            async for message in adapter.subscribe():
                if not self.dm_policy.allow(message.channel_id, message.sender.id):
                    logger.debug("[gateway] DM policy blocked channel=%s peer=%s",
                                 message.channel_id, message.sender.id)
                    continue
                envelope = InboundEnvelope(
                    channel_id=message.channel_id,
                    peer_id=message.sender.id,
                    content=message.content,
                    message_id=message.id,
                    thread_id=message.thread_id or "",
                    reply_to_id=message.reply_to_id or "",
                )
                asyncio.create_task(
                    self.handle_inbound(envelope, peer_id=message.sender.id)
                )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[gateway] listener error channel=%s: %s", adapter.channel_id, exc)

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------

    async def handle_inbound(self, envelope: InboundEnvelope, peer_id: str) -> None:
        """Route an inbound message through the agent turn loop."""
        if not self.dm_policy.allow(envelope.channel_id, peer_id):
            return

        agent_id = self.resolver.resolve(envelope)
        turn = self.agent_registry.get_turn(agent_id)
        if turn is None:
            logger.error("[gateway] no turn for agent=%s", agent_id)
            return

        session_key = self.session_key_builder.build(
            agent_id=agent_id,
            channel_id=envelope.channel_id,
            peer_id=envelope.peer_id,
        )

        lock = self.session_manager.lock_for(session_key)
        async with lock:
            await self._run_turn(
                agent_id=agent_id,
                session_key=session_key,
                envelope=envelope,
                turn=turn,
                peer_id=peer_id,
            )

    async def _run_turn(self, agent_id, session_key, envelope, turn, peer_id) -> None:
        agent_cfg = self.agent_registry.get_agent_config(agent_id)
        execution_unit_id = str(uuid.uuid4())

        # Detect new session before appending user message
        is_new_session = len(self.session_manager.get_messages(session_key)) == 0

        # Workspace + skills + memory + system prompt
        workspace_files = self.workspace_bootstrapper.load(agent_id)
        skills = self.skill_gate.filter(self.skill_loader.load(agent_id=agent_id))
        skills_block = self.skills_injector.build_block(skills)

        memories = await self.memory_manager.recall(agent_id, envelope.content, limit=5)
        memories_block = self.memory_injector.build_block(memories)

        knowledge_block = ""
        if self.knowledge_retriever is not None and self.knowledge_injector is not None:
            knowledge_chunks = await self.knowledge_retriever.retrieve(
                query=envelope.content,
                workspace_id=agent_id,
            )
            knowledge_block = self.knowledge_injector.build_block(knowledge_chunks)

        prompt_ctx = PromptContext(
            agent_id=agent_id,
            agent_name=agent_cfg.name if agent_cfg else agent_id,
            workspace_files=workspace_files,
            skills_block=skills_block,
            memories_block=memories_block,
            knowledge_block=knowledge_block,
        )
        system_prompt = self.agent_registry.get_prompt_builder().build(prompt_ctx)

        # Session
        self.session_manager.append_user_message(session_key, envelope.content)
        messages = await self.session_manager.compact_if_needed(session_key, turn)
        self.session_manager.prune_if_needed(session_key)

        # Determine delivery mode: stream to WebChat, collect+send to others
        adapter = self.channel_registry.get(envelope.channel_id)
        is_webchat = isinstance(adapter, WebChatAdapter)

        async def on_chunk(chunk: str) -> None:
            if is_webchat:
                await self.webchat_adapter.stream_chunk(peer_id, chunk)

        # Scoped executor: injects agent_id + execution_unit_id into memory and
        # workspace tool inputs so handlers know which agent's store to use.
        from claw.memory.tools import is_memory_tool
        from claw.workspace.tools import is_workspace_tool
        _base_exec = self.tool_registry.executor()

        async def scoped_executor(name: str, inp: dict):
            if is_memory_tool(name) or is_workspace_tool(name):
                inp = {
                    "_agent_id": agent_id,
                    "_execution_unit_id": execution_unit_id,
                    **inp,
                }
            return await _base_exec(name, inp)

        if self._aindy and self.config.aindy.emit_events:
            if is_new_session:
                asyncio.create_task(_emit_aindy(self._aindy, "claw.session.started", {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "channel": envelope.channel_id,
                    "execution_unit_id": execution_unit_id,
                }))
            asyncio.create_task(_emit_aindy(self._aindy, "sys.v1.claw.turn.start", {
                "agent_id": agent_id,
                "session_key": session_key,
                "execution_unit_id": execution_unit_id,
            }))

        try:
            result = await turn.run(
                messages=messages,
                system=system_prompt,
                tools=self.tool_registry.definitions() or None,
                on_chunk=on_chunk,
                tool_executor=scoped_executor,
                max_tokens=self.config.agents.defaults.model.max_tokens,
                temperature=self.config.agents.defaults.model.temperature,
            )
            self.session_manager.append_assistant_message(session_key, result["content"])

            if self._aindy and self.config.aindy.emit_events:
                asyncio.create_task(_emit_aindy(self._aindy, "sys.v1.claw.turn.complete", {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "execution_unit_id": execution_unit_id,
                    "response_len": len(result["content"]),
                }))

            # Deliver response
            if is_webchat:
                await self.webchat_adapter.send_done(peer_id)
            elif adapter and result["content"]:
                # Split long responses for channels with message length limits
                from claw.agents.streaming import split_blocks
                max_len = adapter.info.max_message_length
                blocks = split_blocks(result["content"], max_block=max_len)
                for block in blocks:
                    await adapter.send(block, peer_id, thread_id=envelope.thread_id)

        except Exception as exc:
            logger.error("[gateway] turn error agent=%s: %s", agent_id, exc)
            if self._aindy and self.config.aindy.emit_events:
                asyncio.create_task(_emit_aindy(self._aindy, "sys.v1.claw.turn.error", {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "execution_unit_id": execution_unit_id,
                    "error": str(exc)[:200],
                }))
            if is_webchat:
                await self.webchat_adapter.send_error(peer_id, str(exc))
            elif adapter:
                try:
                    await adapter.send(f"[error: {exc}]", peer_id)
                except Exception:
                    pass


# ------------------------------------------------------------------
# FastAPI app factory
# ------------------------------------------------------------------

async def _emit_aindy(client, event_type: str, payload: dict) -> None:
    try:
        await client.emit_event(event_type, payload)
    except Exception as exc:
        logger.debug("[gateway] AINDY event skipped %s: %s", event_type, exc)


def _build_claw_router(gateway: ClawGateway, config: ClawConfig) -> APIRouter:
    """Build the Claw APIRouter — all Claw-specific routes.

    Works in both standalone FastAPI mode (included via app.include_router)
    and AINDY mounted mode (registered via claw.aindy.app_registration).
    Health, ready, and observability are NOT included here; they are either
    added by build_app() in standalone mode or provided by AINDY in mounted mode.
    """
    router = APIRouter()

    # WebChat UI
    static_dir = _resolve_static_dir(config)
    if static_dir and static_dir.exists():
        _index_path = str(static_dir / "index.html")

        @router.get("/")
        async def webchat_ui():
            return FileResponse(_index_path, media_type="text/html")

    # WebChat WS
    @router.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket, token: Optional[str] = None):
        await gateway.auth.verify_ws(websocket, token)
        await websocket.accept()

        _t0 = time.monotonic()
        _session_info: dict = {}

        async def on_message(envelope: InboundEnvelope) -> None:
            if not _session_info:
                agent_id = gateway.resolver.resolve(envelope)
                _session_info["agent_id"] = agent_id
                _session_info["session_key"] = gateway.session_key_builder.build(
                    agent_id=agent_id,
                    channel_id=envelope.channel_id,
                    peer_id=envelope.peer_id,
                )
            await gateway.handle_inbound(envelope, peer_id=envelope.peer_id)

        await gateway.webchat_adapter.handle_ws_connection(
            websocket,
            on_message=on_message,
        )

        # WebSocket closed — emit session.ended if AINDY is active
        if _session_info and gateway._aindy and gateway.config.aindy.emit_events:
            duration_ms = int((time.monotonic() - _t0) * 1000)
            asyncio.create_task(_emit_aindy(gateway._aindy, "claw.session.ended", {
                "agent_id": _session_info.get("agent_id", ""),
                "session_key": _session_info.get("session_key", ""),
                "duration_ms": duration_ms,
                "channel": "webchat",
            }))

    # Control-plane WS (stub; full nodus_protocol in Phase 3.9)
    @router.websocket("/ws")
    async def ws_control(websocket: WebSocket, token: Optional[str] = None):
        await gateway.auth.verify_ws(websocket, token)
        await websocket.accept()
        import json as _json
        await websocket.send_text(_json.dumps({
            "type": "hello",
            "version": "1.0",
            "note": "control-plane WS — stub",
        }))
        try:
            async for _ in websocket.iter_text():
                pass
        except WebSocketDisconnect:
            pass

    # Pairing API
    @router.post("/pair/generate", include_in_schema=False)
    async def pair_generate(channel_id: str, peer_id: str):
        code = gateway.pairing_store.generate_code(channel_id, peer_id)
        return {"code": code, "ttl_seconds": 300}

    @router.post("/pair/approve", include_in_schema=False)
    async def pair_approve(code: str):
        record = gateway.pairing_store.approve(code)
        if record is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid or expired pairing code")
        gateway.dm_policy.add_paired_peer(record.channel_id, record.peer_id)
        return {"approved": True, "channel_id": record.channel_id, "peer_id": record.peer_id}

    # Auth — token issuance and API key management
    @router.post("/auth/token", include_in_schema=False)
    async def auth_token(user_id: str, secret: str):
        from fastapi import HTTPException
        if not gateway.auth_manager.is_enabled():
            raise HTTPException(status_code=404, detail="Auth not enabled")
        if secret != (config.gateway.token or ""):
            raise HTTPException(status_code=403, detail="Invalid secret")
        tok = gateway.auth_manager.issue_token(user_id)
        return {"token": tok, "type": "bearer"}

    @router.post("/auth/keys", include_in_schema=False)
    async def auth_keys_create(label: str, scopes: str = "*"):
        from fastapi import HTTPException
        if not gateway.auth_manager.is_enabled():
            raise HTTPException(status_code=404, detail="Auth not enabled")
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
        raw_key, record = gateway.auth_manager.api_key_store.create(
            label=label, scopes=scope_list or ["*"]
        )
        return {
            "key": raw_key,
            "key_id": record.key_id,
            "label": record.label,
            "scopes": record.scopes,
        }

    @router.get("/auth/keys", include_in_schema=False)
    async def auth_keys_list():
        keys = gateway.auth_manager.api_key_store.list_keys()
        return {"keys": [
            {
                "key_id": k.key_id, "label": k.label, "scopes": k.scopes,
                "created_at": k.created_at.isoformat(),
                "last_used": k.last_used.isoformat() if k.last_used else None,
            }
            for k in keys
        ]}

    @router.delete("/auth/keys/{key_id}", include_in_schema=False)
    async def auth_keys_revoke(key_id: str):
        revoked = gateway.auth_manager.api_key_store.revoke(key_id)
        if not revoked:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Key not found")
        return {"revoked": True, "key_id": key_id}

    return router


def build_app(config: ClawConfig) -> tuple[FastAPI, ClawGateway]:
    """Build the FastAPI app and gateway, wired together.

    Standalone mode (aindy.mounted = False, the default): creates a complete
    FastAPI app with health endpoints, observability, and all Claw routes.

    Mounted mode (aindy.mounted = True): creates a minimal app with only
    Claw's routes — health/observability come from the AINDY platform layer.
    Production mounted deployments should use
    ``claw.aindy.app_registration.register_claw_app()`` instead.

    build_app() always returns (FastAPI, ClawGateway) — this signature is
    test-critical; do not change it.
    """
    gateway = ClawGateway(config)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        await gateway.startup()
        yield
        await gateway.shutdown()

    app = FastAPI(title="Claw Gateway", version="0.1.0", lifespan=_lifespan)

    # Standalone-only: health + observability.
    # In mounted mode these are provided by the AINDY platform layer.
    if not config.aindy.mounted:
        @app.get("/health", include_in_schema=False)
        async def health():
            return {"status": "ok", "service": "claw-gateway"}

        @app.get("/ready", include_in_schema=False)
        async def ready():
            return {"status": "ready"}

        try:
            from nodus_observability_framework import init_observability
            init_observability(
                app,
                service_name="claw-gateway",
                env=os.environ.get("CLAW_ENV", "development"),
                log_level=config.log_level,
                include_health_router=False,
            )
        except Exception as exc:
            logger.warning("[gateway] observability init skipped: %s", exc)

    # Claw routes — work in both standalone and mounted mode.
    app.include_router(_build_claw_router(gateway, config))

    return app, gateway


def _resolve_static_dir(config: ClawConfig) -> Optional[Path]:
    if config.channels.webchat.static_dir:
        p = Path(config.channels.webchat.static_dir).expanduser()
        return p if p.exists() else None
    pkg_static = Path(__file__).parent.parent.parent / "claw_webchat" / "static"
    return pkg_static if pkg_static.exists() else None
