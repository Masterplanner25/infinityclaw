# Test Strategy — Infinity Claw

---

## Running tests

```powershell
venv\Scripts\python.exe -m pytest tests/ -q          # full suite
venv\Scripts\python.exe -m pytest tests/ -q -x       # stop on first failure
venv\Scripts\python.exe -m pytest tests/test_aindy_phase12.py -v  # single file
venv\Scripts\python.exe -m pytest tests/ -k "weave"  # filter by name
```

**Baseline: 218/218 tests must always pass.** Never merge a change that breaks this.

---

## Configuration

`asyncio_mode = "auto"` is set in `pyproject.toml`. Every `async def test_*` function is automatically treated as an async test. Do not add `@pytest.mark.asyncio` — it is redundant and was removed.

All tests use in-memory SQLite (`db_path=":memory:"`). No filesystem state is created or leaked between tests.

---

## Suite layout

16 test files across three generations:

### Generation 1 — Original milestone tests (30 functions)

Written before the AINDY integration. Test the foundational gateway layer against the live ASGI app.

| File | Functions | Coverage |
|---|---|---|
| `test_phase4_milestone.py` | 12 | Gateway startup, routing, WebSocket, session compaction, tool registry, memory injection |
| `test_phase5_milestone.py` | 10 | Memory CRUD, session key scoping, auth (JWT + API keys + static token) |
| `test_phase6_milestone.py` | 8 | SQLite persistence, browser tool (`browser_fetch`), CLI doctor output |

These tests use `httpx.AsyncClient(app=app, base_url=...)` to drive the real ASGI app without a network. They are the closest thing to integration tests in the suite.

### Generation 2 — AINDY phase tests (88 functions, phases 2–9)

Unit-oriented. Each file covers one integration phase. No real AINDY server, no real LLM, no network. Mock clients and `:memory:` SQLite throughout.

| File | Functions | Phase covered |
|---|---|---|
| `test_aindy_phase2.py` | 10 | AINDY memory backend (`AINDYMemoryStore`, `aindy-fallback`, `local`) |
| `test_aindy_phase3.py` | 9 | Execution tracking (`execution_unit_id`, `claw.session.*`, `claw.memory.written`) |
| `test_aindy_phase4.py` | 11 | Gateway mount (`_build_claw_router`, `build_app` modes, `GatewayAuth` bypass) |
| `test_aindy_phase5.py` | 12 | Knowledge layer (ingestion, chunking, FTS5 index, retrieval, scanner) |
| `test_aindy_phase6.py` | 12 | Workspace objects (store, manager, documents, tasks, permissions) |
| `test_aindy_phase7.py` | 16 | Permissions (`CapabilitySet`, `PermissionEnforcer`, HTTP/tool/skill gating, watcher) |
| `test_aindy_phase8.py` | 14 | Multi-agent coordination (dispatcher, `delegate_to_agent`, skill gating, cross-agent memory) |
| `test_aindy_phase9.py` | 18 | Cross-workspace tool access (`target_agent_id`, implicit permission on ID-based tools) |

### Generation 3 — Later phase tests (100 functions, phases 10–14)

Same unit-oriented approach. Heavier use of source inspection (`inspect.getsource`) to verify wiring that cannot easily be observed through function call results.

| File | Functions | Phase covered |
|---|---|---|
| `test_aindy_phase10.py` | 13 | Session-persistent delegation (session key derivation, `run_agent_turn` history) |
| `test_aindy_phase11.py` | 11 | Delegation audit trail (AINDY events per dispatch, `delegation_id`, unknown-agent case) |
| `test_aindy_phase12.py` | 28 | Weave (node store, `WeaveClient` resilience, tools, REST endpoints, session key) |
| `test_aindy_phase13.py` | 16 | Cross-node workspace federation (client methods, federation tools, REST endpoints) |
| `test_aindy_phase14.py` | 18 | Weave-wide discovery + cross-node writes (list_all_agents, write tools, knowledge endpoint) |

---

## Testing patterns

### Source inspection

Many behaviors are wiring decisions inside `_run_turn` or `scoped_executor` that cannot be observed through function return values. These are verified with `inspect.getsource`:

```python
def test_session_key_injected_for_weave_tools():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._run_turn)
    assert "is_weave_tool" in src
    assert "_session_key" in src
```

This is intentional: it catches regressions where a wiring line is accidentally deleted during refactors.

### Resilience tests

`WeaveClient` and `AgentDispatcher` are tested against failure by pointing them at unreachable ports:

```python
node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
result = await client.fetch_document(node, "researcher", "doc-id")
assert result is None   # never raises
```

### Mock clients

Tests that need AINDY behaviour use a `MagicMock` with `AsyncMock` methods rather than a real AINDY server. The mock is passed directly to `MemoryManager` or `AgentDispatcher`.

### In-memory SQLite

Every test that touches a database passes `db_path=":memory:"`. Never use an empty string — that hits `~/.claw/memory.db` and leaks state across test runs.

---

## What is covered

- Config schema: all fields, defaults, validators, alias handling
- Memory: SQLite CRUD, AINDY delegation, fallback logic, async public methods
- Sessions: compaction, pruning, key scoping
- Auth: JWT issuance and verification, API key create/list/revoke, static token, bypass mode
- Skills: loading, global gate, per-agent gate, wildcard allow
- Knowledge: file parsing, chunking with overlap, FTS5 upsert/search/clear, retrieval, watcher source wiring
- Workspace: store CRUD, manager async wrapper, all six `ws_*` tools, cross-workspace permissions
- Permissions: `filter_tool_definitions`, `check_tool_call`, HTTP allowlist/denylist, private network block
- Coordination: dispatcher happy path, unknown-agent error, session key derivation, cross-agent memory source wiring
- Weave: node store CRUD, all 11 weave tools, REST endpoint source wiring, session key derivation, skip-failed-nodes pattern
- AINDY bridge: mounted mode auth bypass, event emission wiring, memory backend routing

---

## What is NOT covered

| Gap | Reason |
|---|---|
| Channel adapters (Discord, Telegram, Slack, Matrix, Signal) | Require real external services and credentials |
| Live LLM turns | No real Anthropic API calls in tests; the turn pipeline is exercised via ASGI but with mocked responses |
| Cron job execution | Timing-dependent; verified via source inspection only |
| Live WebSocket connections in generation 2/3 tests | The WS handler is exercised in generation 1 milestone tests only |
| Real AINDY server integration | Tested via mocks; the SDK call paths are not exercised end-to-end |
| Real Weave cross-node HTTP | Client resilience tested against a closed port; no two live Claw instances |
| E2EE for Matrix | Not implemented yet |

---

## Adding new tests

When adding a new phase or subsystem:

1. Create `tests/test_aindy_phase<N>.py` (or an appropriately named file)
2. Add a module docstring listing what's covered and the assertion/function count
3. Use `":memory:"` for all database paths
4. Do not add `@pytest.mark.asyncio` — it is applied automatically
5. Do not make real network calls — mock or point at `127.0.0.1:59999` for resilience tests
6. Verify the baseline: `pytest tests/ -q` must show all tests passing before committing
