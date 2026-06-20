"""AINDY platform layer integration — register Claw as a mounted sub-app.

Usage (inside an AINDY platform layer bootstrap):

    from claw.aindy.app_registration import register_claw_app

    gateway = await register_claw_app(config_path="/etc/claw/claw.toml", prefix="/claw")
    # gateway.startup() has already been called; shutdown is caller's responsibility.
    await gateway.shutdown()

In standalone mode, use ``claw.gateway.server.build_app()`` instead.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def register_claw_app(
    config_path: Optional[str] = None,
    prefix: str = "/claw",
) -> "ClawGateway":  # noqa: F821
    """Build and register Claw routes with the AINDY platform layer.

    Forces ``aindy.mounted = True`` so health/observability routes are
    skipped (the platform layer provides them) and ``GatewayAuth`` enters
    bypass mode (AINDY has already authenticated the request).

    Returns the started ClawGateway.  The caller is responsible for calling
    ``gateway.shutdown()`` on teardown.

    If ``AINDY.platform_layer.registry`` is not available (e.g. running in a
    test or lightweight environment) a warning is logged and the router is
    returned without registering — callers can mount it manually.
    """
    from claw.config.loader import load_config
    from claw.gateway.server import ClawGateway, _build_claw_router

    config = load_config(config_path)
    config.aindy.mounted = True  # enforce mounted semantics

    gateway = ClawGateway(config)
    await gateway.startup()

    router = _build_claw_router(gateway, config)

    try:
        from AINDY.platform_layer.registry import register_router  # type: ignore[import]
        register_router(router)
        logger.info("[claw] registered Claw routes via AINDY platform layer (prefix=%s applied by caller)", prefix)
    except ImportError:
        logger.warning(
            "[claw] AINDY.platform_layer not available — "
            "mount the router manually: app.include_router(router, prefix='%s')",
            prefix,
        )

    return gateway
