"""AINDY Phase 4 milestone test — Gateway Mount.

Tests (no real server or AINDY needed):
- _build_claw_router() returns an APIRouter with expected routes
- build_app() standalone: includes /health and /ready
- build_app() mounted: omits /health and /ready
- GatewayAuth(bypass=False) normal operation unchanged
- GatewayAuth(bypass=True) returns aindy principal for any token
- register_claw_app() handles missing AINDY.platform_layer gracefully
- Existing test suite (Phases 1-3) passes as regression

Run:  python tests/test_aindy_phase4.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


def _collect_paths(routes) -> set[str]:
    """Recursively collect route paths, unwrapping _IncludedRouter containers."""
    paths: set[str] = set()
    for r in routes:
        path = getattr(r, "path", None)
        if path is not None:
            paths.add(path)
        # FastAPI wraps include_router() in _IncludedRouter — walk into original_router
        if hasattr(r, "original_router"):
            paths |= _collect_paths(r.original_router.routes)
        elif hasattr(r, "routes"):
            paths |= _collect_paths(r.routes)
    return paths


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _minimal_config(mounted: bool = False):
    """Build a minimal ClawConfig with a fake credential (no LLM calls made)."""
    from claw.config.schema import ClawConfig, CredentialConfig, MemoryConfig
    cfg = ClawConfig()
    # Fake credential — never used in network calls; just satisfies AgentRegistry init.
    cfg.credentials = [CredentialConfig(id="test", provider="anthropic", api_key="sk-ant-test-fake")]
    cfg.memory = MemoryConfig(enabled=True, db_path=":memory:")
    cfg.aindy.mounted = mounted
    return cfg


# ------------------------------------------------------------------
# 1. _build_claw_router returns an APIRouter
# ------------------------------------------------------------------

def test_build_claw_router_type() -> None:
    print("\n== _build_claw_router returns APIRouter ==")
    try:
        from fastapi import APIRouter
        from claw.config.schema import ClawConfig, MemoryConfig
        from claw.gateway.server import ClawGateway, _build_claw_router

        cfg = _minimal_config()
        gateway = ClawGateway(cfg)
        router = _build_claw_router(gateway, cfg)

        assert isinstance(router, APIRouter), f"expected APIRouter, got {type(router)}"
        check("_build_claw_router returns APIRouter", PASS)
    except Exception as e:
        check("_build_claw_router returns APIRouter", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. Router has expected routes
# ------------------------------------------------------------------

def test_router_has_expected_routes() -> None:
    print("\n== Router has expected routes ==")
    try:
        from claw.gateway.server import ClawGateway, _build_claw_router

        cfg = _minimal_config()
        gateway = ClawGateway(cfg)
        router = _build_claw_router(gateway, cfg)

        paths = _collect_paths(router.routes)

        expected = {"/ws/chat", "/ws", "/pair/generate", "/pair/approve",
                    "/auth/token", "/auth/keys", "/auth/keys/{key_id}"}
        missing = expected - paths
        assert not missing, f"missing routes: {missing}"
        check("Router contains all expected routes", PASS, f"{len(paths)} routes")
    except Exception as e:
        check("Router expected routes", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. build_app() standalone includes /health and /ready
# ------------------------------------------------------------------

def test_build_app_standalone_has_health() -> None:
    print("\n== build_app() standalone includes /health and /ready ==")
    try:
        from claw.gateway.server import build_app

        cfg = _minimal_config(mounted=False)
        app, gateway = build_app(cfg)

        paths = _collect_paths(app.routes)
        assert "/health" in paths, f"/health missing from standalone app routes: {paths}"
        assert "/ready" in paths, f"/ready missing from standalone app routes: {paths}"
        check("Standalone app has /health", PASS)
        check("Standalone app has /ready", PASS)
    except Exception as e:
        check("Standalone app health routes", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. build_app() mounted omits /health and /ready
# ------------------------------------------------------------------

def test_build_app_mounted_omits_health() -> None:
    print("\n== build_app() mounted omits /health and /ready ==")
    try:
        from claw.gateway.server import build_app

        cfg = _minimal_config(mounted=True)
        app, gateway = build_app(cfg)

        paths = _collect_paths(app.routes)
        assert "/health" not in paths, f"/health should not appear in mounted app, but found: {paths}"
        assert "/ready" not in paths, f"/ready should not appear in mounted app, but found: {paths}"
        check("Mounted app omits /health", PASS)
        check("Mounted app omits /ready", PASS)
    except Exception as e:
        check("Mounted app omits health routes", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. Mounted app still includes claw routes
# ------------------------------------------------------------------

def test_build_app_mounted_has_claw_routes() -> None:
    print("\n== build_app() mounted still includes Claw routes ==")
    try:
        from claw.gateway.server import build_app

        cfg = _minimal_config(mounted=True)
        app, gateway = build_app(cfg)

        paths = _collect_paths(app.routes)
        for expected in ("/ws/chat", "/pair/generate", "/auth/token"):
            assert expected in paths, f"{expected} missing from mounted app"
        check("Mounted app retains Claw routes", PASS, f"{len(paths)} routes total")
    except Exception as e:
        check("Mounted app Claw routes", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. GatewayAuth bypass=False — normal operation
# ------------------------------------------------------------------

async def test_gateway_auth_bypass_false() -> None:
    print("\n== GatewayAuth(bypass=False) normal operation ==")
    try:
        from claw.gateway.auth import GatewayAuth

        # No token, no auth manager -> open mode
        auth = GatewayAuth(bypass=False)
        assert auth.enabled is False, "No token -> should be disabled"
        principal = auth.verify_principal(None)
        assert principal is not None
        assert principal.auth_type == "open"
        check("GatewayAuth(bypass=False) open mode works", PASS)

        # With static token
        auth2 = GatewayAuth(static_token="secret123", bypass=False)
        assert auth2.enabled is True
        p2 = auth2.verify_principal("secret123")
        assert p2 is not None and p2.auth_type == "static"
        p3 = auth2.verify_principal("wrong")
        assert p3 is None
        check("GatewayAuth(bypass=False) static token works", PASS)
    except Exception as e:
        check("GatewayAuth bypass=False", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. GatewayAuth bypass=True — always aindy principal
# ------------------------------------------------------------------

async def test_gateway_auth_bypass_true() -> None:
    print("\n== GatewayAuth(bypass=True) returns aindy principal ==")
    try:
        from claw.gateway.auth import GatewayAuth

        auth = GatewayAuth(static_token="secret123", bypass=True)
        assert auth.enabled is False, "bypass=True -> enabled must be False"

        # No token -> aindy principal
        p = auth.verify_principal(None)
        assert p is not None
        assert p.user_id == "aindy"
        assert p.auth_type == "aindy"
        assert "*" in p.scopes
        check("bypass=True -> enabled is False", PASS)
        check("bypass=True -> verify_principal returns aindy principal (no token)", PASS)

        # Wrong token -> still aindy principal (bypass overrides all checks)
        p2 = auth.verify_principal("garbage")
        assert p2 is not None and p2.auth_type == "aindy"
        check("bypass=True -> verify_principal returns aindy principal (wrong token)", PASS)
    except Exception as e:
        check("GatewayAuth bypass=True", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. ClawGateway uses bypass when mounted
# ------------------------------------------------------------------

def test_gateway_auth_wired_from_config() -> None:
    print("\n== ClawGateway wires bypass=True when mounted ==")
    try:
        from claw.gateway.server import ClawGateway

        cfg_mounted = _minimal_config(mounted=True)
        gw_mounted = ClawGateway(cfg_mounted)
        assert gw_mounted.auth._bypass is True, "mounted gateway should have bypass=True"
        check("ClawGateway mounted -> auth._bypass is True", PASS)

        cfg_standalone = _minimal_config(mounted=False)
        gw_standalone = ClawGateway(cfg_standalone)
        assert gw_standalone.auth._bypass is False, "standalone gateway should have bypass=False"
        check("ClawGateway standalone -> auth._bypass is False", PASS)
    except Exception as e:
        check("ClawGateway auth wiring", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. register_claw_app() gracefully handles missing platform layer
# ------------------------------------------------------------------

async def test_register_claw_app_no_platform() -> None:
    print("\n== register_claw_app() handles missing AINDY platform layer ==")
    try:
        # Provide a fake key via env so load_config() inside register_claw_app succeeds.
        import os as _os
        _os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-fake")

        from claw.aindy.app_registration import register_claw_app

        # AINDY.platform_layer is not installed in test env — should warn and return gateway
        gateway = await register_claw_app(config_path=str(ROOT / "claw.toml"), prefix="/claw")
        assert gateway is not None, "register_claw_app should return a ClawGateway"
        assert gateway.config.aindy.mounted is True, "mounted flag should be forced True"
        check("register_claw_app returns gateway without platform layer", PASS)

        # Cleanup
        try:
            await gateway.shutdown()
        except Exception:
            pass

    except Exception as e:
        check("register_claw_app no platform layer", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. build_app signature unchanged (test-critical)
# ------------------------------------------------------------------

def test_build_app_signature() -> None:
    print("\n== build_app() signature unchanged ==")
    try:
        from claw.gateway.server import build_app
        import inspect

        sig = inspect.signature(build_app)
        params = list(sig.parameters)
        assert params == ["config"], f"unexpected params: {params}"
        check("build_app(config) signature unchanged", PASS)
    except Exception as e:
        check("build_app signature", FAIL, str(e))
        traceback.print_exc()


# ------------------------------------------------------------------
# 11. Regression: full pytest suite
# ------------------------------------------------------------------

def test_full_suite_regression() -> None:
    print("\n== Full pytest suite regression ==")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=300,
            cwd=str(ROOT),
        )
        if r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            summary = lines[-1] if lines else ""
            check("Full pytest suite", PASS, summary)
        else:
            tail = (r.stdout + r.stderr)[-400:]
            check("Full pytest suite", FAIL, tail)
    except Exception as e:
        check("Full pytest suite regression", FAIL, str(e))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_gateway_auth_bypass_false()
    await test_gateway_auth_bypass_true()
    await test_register_claw_app_no_platform()


def main() -> None:
    print("=" * 60)
    print("  AINDY Phase 4 -- Gateway Mount")
    print("=" * 60)

    test_build_claw_router_type()
    test_router_has_expected_routes()
    test_build_app_standalone_has_health()
    test_build_app_mounted_omits_health()
    test_build_app_mounted_has_claw_routes()
    asyncio.run(run_async_tests())
    test_gateway_auth_wired_from_config()
    test_build_app_signature()
    test_full_suite_regression()

    print()
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _ in results if s == SKIP)
    total = len(results)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    if skipped:
        print(f", {skipped} skipped", end="")
    print()
    print("=" * 60)

    if failed:
        print("\nFailed tests:")
        for name, status, note in results:
            if status == FAIL:
                print(f"  - {name}: {note}")
        sys.exit(1)


if __name__ == "__main__":
    main()
