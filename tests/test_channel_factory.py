"""[channels.extra.<name>] → a registered adapter.

The gap this covers: the five external adapters were packaged and `register_adapter` existed,
but nothing read `config.channels.extra`, so a configured channel never reached the gateway.
These tests drive the factory directly and assert the gateway's startup calls it.
"""
from __future__ import annotations

import logging

import pytest

from claw.channels.factory import BUILDERS, build_extra_adapters


def test_a_telegram_block_builds_a_registered_telegram_adapter(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    adapters = build_extra_adapters({"telegram": {"token": "123:ABC", "allowed_users": ["42"]}})
    assert len(adapters) == 1
    a = adapters[0]
    assert a.channel_id == "telegram"
    assert a._token == "123:ABC"
    assert a._allowed_users == {"42"}


def test_the_token_may_come_from_the_environment_instead_of_the_file(monkeypatch):
    """A secret belongs in .env, not in a config file that gets committed."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env:TOKEN")
    adapters = build_extra_adapters({"telegram": {}})
    assert len(adapters) == 1 and adapters[0]._token == "env:TOKEN"


def test_allowed_users_accepts_a_comma_string_and_numbers(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    a = build_extra_adapters({"telegram": {"allowed_users": "8228108414, 7"}})[0]
    assert a._allowed_users == {"8228108414", "7"}
    b = build_extra_adapters({"telegram": {"allowed_users": [8228108414]}})[0]
    assert b._allowed_users == {"8228108414"}


def test_a_block_with_no_token_is_skipped_and_named(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="claw.channels.factory"):
        adapters = build_extra_adapters({"telegram": {}})
    assert adapters == []
    assert any("telegram" in r.getMessage() and "TELEGRAM_BOT_TOKEN" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]


def test_enabled_false_keeps_the_block_but_builds_nothing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert build_extra_adapters({"telegram": {"enabled": False}}) == []


def test_an_unknown_channel_is_skipped_with_the_known_ones_named(caplog):
    with caplog.at_level(logging.WARNING, logger="claw.channels.factory"):
        assert build_extra_adapters({"carrier-pigeon": {"token": "x"}}) == []
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "carrier-pigeon" in msg and "telegram" in msg


def test_one_broken_channel_does_not_stop_the_others(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    adapters = build_extra_adapters({"discord": {}, "telegram": {}})
    assert [a.channel_id for a in adapters] == ["telegram"]


def test_every_builder_is_a_channel_the_repo_actually_ships():
    """Derived, not a hand-written list: each builder must import its package."""
    import importlib

    assert BUILDERS, "the builder table must not be empty"
    for name in BUILDERS:
        importlib.import_module(f"claw_{name}")


def test_gateway_startup_actually_calls_the_factory():
    """The whole bug was a factory nobody called: assert the call is IN `startup`, from source.

    An AST walk, not a text match — a mention in a comment or a docstring must not satisfy it.
    """
    import ast
    import inspect

    from claw.gateway import server as server_mod

    tree = ast.parse(inspect.getsource(server_mod))
    startup = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup"
    )
    calls = {
        node.func.id
        for node in ast.walk(startup)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "build_extra_adapters" in calls, sorted(calls)

    registers = [
        node for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register"
    ]
    assert registers, "startup calls the factory but registers nothing"


# ── the registry's send: a receipt, and a refusal ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_returns_the_providers_message_id():
    """The receipt a mediated effect records must come from the PROVIDER, not from us."""
    from claw.channels.registry import ChannelAdapterRegistry

    class _Adapter:
        channel_id = "telegram"
        sent: list = []

        async def send(self, content, peer_id, **kwargs):
            self.sent.append((content, peer_id))
            return "4242"

    reg = ChannelAdapterRegistry()
    reg.register(_Adapter())
    assert await reg.send("telegram", "hi", "8228108414") == "4242"


@pytest.mark.asyncio
async def test_send_to_an_unregistered_channel_raises_instead_of_reading_as_success():
    """It used to log a warning and return, which every caller read as delivered — with the
    effect seam on that wrote a `success` ledger row for a message nobody ever sent."""
    from claw.channels.registry import ChannelAdapterRegistry, ChannelNotRegistered

    reg = ChannelAdapterRegistry()
    with pytest.raises(ChannelNotRegistered) as exc:
        await reg.send("telegram", "hi", "peer")
    assert "telegram" in str(exc.value)


# ── the runtime's own registry, readable from a live Claw ────────────────────────────────

def _cfg(effects_backend: str, monkeypatch):
    from claw.config.loader import load_config

    cfg = load_config("claw.toml")
    cfg.aindy.enabled = effects_backend == "aindy"
    cfg.aindy.effects_backend = effects_backend
    cfg.aindy.database_url = "postgresql://unused:unused@127.0.0.1:1/unused"
    cfg.aindy.user_id = "f33f40c2-9580-4c42-a281-2d507c4eddff"
    return cfg


def _paths(app) -> set:
    """FastAPI wraps sub-routers lazily — `app.routes` holds _IncludedRouter objects with no
    `.path`. Walk them."""
    found = set()
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        path = getattr(r, "path", None)
        if path:
            found.add(path)
        stack.extend(getattr(r, "routes", []) or [])
    return found


def test_metrics_aindy_is_absent_when_the_seam_is_off(monkeypatch):
    """No seam, no runtime registry to read — the route must not exist at all."""
    from claw.gateway.server import build_app

    app, _ = build_app(_cfg("local", monkeypatch))
    assert "/metrics/aindy" not in _paths(app)


def test_metrics_aindy_serves_the_runtime_registry_when_the_seam_is_on(monkeypatch):
    """The gate counter an operator needs lives in AINDY's registry, not nodus-observability's."""
    from claw.gateway.server import build_app

    app, _ = build_app(_cfg("aindy", monkeypatch))
    assert "/metrics/aindy" in _paths(app), sorted(_paths(app))

    from AINDY.platform_layer.metrics import REGISTRY
    names = {m.name for m in REGISTRY.collect()}
    assert "aindy_effect_gate_outcomes" in names, "the gate counter must be in the served registry"
