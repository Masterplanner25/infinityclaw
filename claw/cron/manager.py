"""CronManager — APScheduler-backed scheduled agent jobs."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from nodus_sdk.bridges.scheduler import SchedulerBridge

if TYPE_CHECKING:
    from claw.gateway.server import ClawGateway

logger = logging.getLogger(__name__)


class DeliveryMode(str, Enum):
    ANNOUNCE = "announce"   # send result to the agent's main session
    WEBHOOK = "webhook"     # POST result to a URL
    NONE = "none"           # fire-and-forget, discard result


@dataclass
class CronJob:
    id: str
    agent_id: str
    prompt: str                    # what the agent should do/think about
    cron_expr: str                 # standard 5-part cron expression
    delivery: DeliveryMode = DeliveryMode.ANNOUNCE
    delivery_channel: str = ""     # channel_id for announce delivery
    delivery_peer: str = ""        # peer_id for announce delivery
    webhook_url: str = ""          # URL for webhook delivery
    enabled: bool = True
    last_run: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class CronManager:
    """Manages cron-triggered agent jobs.

    Jobs run as isolated agent turns (fresh session per run) using the
    configured agent. Results are delivered per the job's delivery mode.
    """

    def __init__(self, gateway: "ClawGateway") -> None:
        self._gateway = gateway
        self._bridge = SchedulerBridge(timezone="UTC")
        self._jobs: dict[str, CronJob] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def startup(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._bridge.start()

        # Register jobs from config
        for job_cfg in (self._gateway.config.cron or []):
            try:
                from claw.config.schema import CronJobConfig
                job = CronJob(
                    id=job_cfg.id,
                    agent_id=job_cfg.agent_id,
                    prompt=job_cfg.prompt,
                    cron_expr=job_cfg.cron,
                    delivery=DeliveryMode(job_cfg.delivery),
                    delivery_channel=job_cfg.delivery_channel,
                    delivery_peer=job_cfg.delivery_peer,
                    webhook_url=job_cfg.webhook_url,
                    enabled=job_cfg.enabled,
                )
                self.add_job(job)
            except Exception as exc:
                logger.warning("[cron] failed to register job: %s", exc)

        logger.info("[cron] scheduler started (%d jobs)", len(self._jobs))

    async def shutdown(self) -> None:
        self._bridge.shutdown(wait=False)
        logger.info("[cron] scheduler stopped")

    def add_job(self, job: CronJob) -> CronJob:
        """Register a cron job. Returns the registered job."""
        if not job.id:
            job.id = str(uuid.uuid4())[:8]

        self._bridge.add_cron_job(
            job_id=job.id,
            func=self._make_sync_runner(job),
            cron_expr=job.cron_expr,
        )
        self._jobs[job.id] = job
        logger.info("[cron] registered job=%s cron=%s agent=%s", job.id, job.cron_expr, job.agent_id)
        return job

    def remove_job(self, job_id: str) -> bool:
        result = self._bridge.cancel(job_id)
        if result:
            self._jobs.pop(job_id, None)
        return result

    def list_jobs(self) -> list[dict]:
        scheduled = {j["id"]: j for j in self._bridge.list_jobs()}
        out = []
        for job in self._jobs.values():
            entry = {
                "id": job.id,
                "agent_id": job.agent_id,
                "cron": job.cron_expr,
                "delivery": job.delivery,
                "enabled": job.enabled,
                "last_run": job.last_run,
            }
            if job.id in scheduled:
                entry["next_run"] = scheduled[job.id]["next_run"]
            out.append(entry)
        return out

    def _make_sync_runner(self, job: CronJob):
        """Return a synchronous callable that APScheduler can invoke."""
        manager = self

        def run():
            if manager._loop is None or not job.enabled:
                return
            future = asyncio.run_coroutine_threadsafe(
                manager._run_job(job),
                manager._loop,
            )
            try:
                future.result(timeout=300)
            except Exception as exc:
                logger.error("[cron] job=%s failed: %s", job.id, exc)

        return run

    async def _run_job(self, job: CronJob) -> None:
        """Execute one cron job turn in an isolated session."""
        import datetime
        job.last_run = datetime.datetime.now().isoformat()
        logger.info("[cron] running job=%s agent=%s", job.id, job.agent_id)

        turn = self._gateway.agent_registry.get_turn(job.agent_id)
        if turn is None:
            logger.error("[cron] no turn for agent=%s", job.agent_id)
            return

        # Isolated session per job run
        session_key = f"cron:{job.id}:{job.last_run[:10]}"
        workspace_files = self._gateway.workspace_bootstrapper.load(job.agent_id)
        agent_cfg = self._gateway.agent_registry.get_agent_config(job.agent_id)
        from claw.agents.prompt import PromptContext
        prompt_ctx = PromptContext(
            agent_id=job.agent_id,
            agent_name=agent_cfg.name if agent_cfg else job.agent_id,
            workspace_files=workspace_files,
        )
        system_prompt = self._gateway.agent_registry.get_prompt_builder().build(prompt_ctx)

        try:
            result = await turn.run(
                messages=[{"role": "user", "content": job.prompt}],
                system=system_prompt,
                tools=self._gateway.tool_registry.definitions() or None,
                tool_executor=self._gateway.tool_registry.executor(),
            )
            response = result.get("content", "")
            await self._deliver(job, response)
        except Exception as exc:
            logger.error("[cron] job=%s run error: %s", job.id, exc)

    async def _deliver(self, job: CronJob, response: str) -> None:
        if not response or job.delivery == DeliveryMode.NONE:
            return

        if job.delivery == DeliveryMode.ANNOUNCE and job.delivery_channel and job.delivery_peer:
            adapter = self._gateway.channel_registry.get(job.delivery_channel)
            if adapter:
                await adapter.send(response, job.delivery_peer)
            else:
                logger.warning("[cron] no adapter for delivery channel=%s", job.delivery_channel)

        elif job.delivery == DeliveryMode.WEBHOOK and job.webhook_url:
            await self._post_webhook(job.webhook_url, response)

    async def _post_webhook(self, url: str, content: str) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"content": content})
        except Exception as exc:
            logger.warning("[cron] webhook POST failed url=%s: %s", url, exc)
