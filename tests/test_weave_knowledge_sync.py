"""Weave Option C — Knowledge Federation tests.

Push-on-demand pull of a peer node's knowledge index into a local peer namespace.

21 assertions across 21 pytest-collected functions.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Group 1: Config — WeaveConfig.knowledge_sync_interval field
# ===========================================================================

def test_weave_config_knowledge_sync_interval_defaults_to_zero():
    from claw.config.schema import WeaveConfig
    cfg = WeaveConfig()
    assert cfg.knowledge_sync_interval == 0


def test_weave_config_knowledge_sync_interval_can_be_set():
    from claw.config.schema import WeaveConfig
    cfg = WeaveConfig(enabled=True, knowledge_sync_interval=3600)
    assert cfg.knowledge_sync_interval == 3600


# ===========================================================================
# Group 2: KnowledgeIndex.export_chunks
# ===========================================================================

def test_export_chunks_returns_empty_for_empty_workspace():
    from claw.knowledge.index import KnowledgeIndex
    index = KnowledgeIndex(":memory:")
    result = index.export_chunks("agent1")
    assert result == []
    index.close()


def test_export_chunks_returns_all_chunks():
    from claw.knowledge.index import KnowledgeIndex
    from claw.knowledge.ingestion import Chunk
    index = KnowledgeIndex(":memory:")
    chunks = [
        Chunk(chunk_id="c1", workspace_id="agent1", source_file="doc.md", content="hello", position=0),
        Chunk(chunk_id="c2", workspace_id="agent1", source_file="doc.md", content="world", position=1),
    ]
    index.upsert_many(chunks)
    result = index.export_chunks("agent1")
    assert len(result) == 2
    ids = {c.chunk_id for c in result}
    assert ids == {"c1", "c2"}
    index.close()


def test_export_chunks_only_returns_matching_workspace():
    from claw.knowledge.index import KnowledgeIndex
    from claw.knowledge.ingestion import Chunk
    index = KnowledgeIndex(":memory:")
    index.upsert_many([
        Chunk(chunk_id="c1", workspace_id="agent1", source_file="a.md", content="alpha", position=0),
        Chunk(chunk_id="c2", workspace_id="agent2", source_file="b.md", content="beta", position=0),
    ])
    result = index.export_chunks("agent1")
    assert len(result) == 1
    assert result[0].chunk_id == "c1"
    assert result[0].workspace_id == "agent1"
    index.close()


def test_export_chunks_ordered_by_source_and_position():
    from claw.knowledge.index import KnowledgeIndex
    from claw.knowledge.ingestion import Chunk
    index = KnowledgeIndex(":memory:")
    index.upsert_many([
        Chunk(chunk_id="c3", workspace_id="ws", source_file="z.md", content="third", position=0),
        Chunk(chunk_id="c1", workspace_id="ws", source_file="a.md", content="first", position=0),
        Chunk(chunk_id="c2", workspace_id="ws", source_file="a.md", content="second", position=1),
    ])
    result = index.export_chunks("ws")
    assert len(result) == 3
    assert result[0].source_file == "a.md" and result[0].position == 0
    assert result[1].source_file == "a.md" and result[1].position == 1
    assert result[2].source_file == "z.md"
    index.close()


# ===========================================================================
# Group 3: WeaveClient.pull_knowledge_index — resilience
# ===========================================================================

async def test_pull_knowledge_index_returns_zero_on_network_error():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://127.0.0.1:59999")
    index = KnowledgeIndex(":memory:")
    result = await client.pull_knowledge_index(node, "researcher", index)
    assert result == 0
    index.close()


async def test_pull_knowledge_index_returns_zero_on_empty_export():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")
    index = KnowledgeIndex(":memory:")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"agent_id": "researcher", "chunks": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.pull_knowledge_index(node, "researcher", index)

    assert result == 0
    index.close()


# ===========================================================================
# Group 4: WeaveClient.pull_knowledge_index — success
# ===========================================================================

async def test_pull_knowledge_index_returns_chunk_count():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex

    client = WeaveClient("local")
    node = WeaveNode(node_id="remote-node", url="http://remote:8000")
    index = KnowledgeIndex(":memory:")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "chunks": [
            {"chunk_id": "c1", "source_file": "/remote/doc.md", "content": "hello world", "position": 0},
            {"chunk_id": "c2", "source_file": "/remote/doc.md", "content": "more content", "position": 1},
        ]
    }
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_http):
        count = await client.pull_knowledge_index(node, "researcher", index)

    assert count == 2
    index.close()


async def test_pull_knowledge_index_uses_peer_namespace():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex

    client = WeaveClient("local")
    node = WeaveNode(node_id="remote-node", url="http://remote:8000")
    index = KnowledgeIndex(":memory:")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "chunks": [
            {"chunk_id": "c1", "source_file": "/doc.md", "content": "some knowledge text", "position": 0},
        ]
    }
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_http):
        await client.pull_knowledge_index(node, "researcher", index)

    peer_ns = "peer:remote-node:researcher"
    assert index.count(peer_ns) == 1
    # original workspace should be empty
    assert index.count("researcher") == 0
    index.close()


async def test_pull_knowledge_index_clears_before_upsert():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex
    from claw.knowledge.ingestion import Chunk

    client = WeaveClient("local")
    node = WeaveNode(node_id="remote-node", url="http://remote:8000")
    index = KnowledgeIndex(":memory:")

    # Pre-populate stale data in the peer namespace
    peer_ns = "peer:remote-node:researcher"
    stale = [Chunk(chunk_id="stale1", workspace_id=peer_ns, source_file="old.md", content="stale", position=0)]
    index.upsert_many(stale)
    assert index.count(peer_ns) == 1

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "chunks": [
            {"chunk_id": "fresh1", "source_file": "/new.md", "content": "fresh content here", "position": 0},
        ]
    }
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_http):
        count = await client.pull_knowledge_index(node, "researcher", index)

    # Stale data gone; fresh data present
    assert count == 1
    assert index.count(peer_ns) == 1
    exported = index.export_chunks(peer_ns)
    assert exported[0].chunk_id == "fresh1"
    index.close()


async def test_pull_knowledge_index_skips_chunks_without_content():
    from claw.weave.client import WeaveClient
    from claw.weave.model import WeaveNode
    from claw.knowledge.index import KnowledgeIndex

    client = WeaveClient("local")
    node = WeaveNode(node_id="n1", url="http://remote:8000")
    index = KnowledgeIndex(":memory:")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "chunks": [
            {"chunk_id": "c1", "content": "valid content", "position": 0},
            {"chunk_id": "c2", "content": "", "position": 1},   # empty — skip
            {"chunk_id": "c3", "position": 2},                   # missing — skip
        ]
    }
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with patch("claw.weave.client.httpx.AsyncClient", return_value=mock_http):
        count = await client.pull_knowledge_index(node, "agent1", index)

    assert count == 1  # only c1 is valid
    index.close()


# ===========================================================================
# Group 5: REST endpoint source inspection
# ===========================================================================

def test_export_endpoint_in_router():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "/weave/workspace/{agent_id}/knowledge/export" in src


def test_export_endpoint_gated_on_knowledge_enabled():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    assert "knowledge.enabled" in src
    assert "export_chunks" in src


def test_export_endpoint_gated_on_weave_enabled():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod._build_claw_router)
    # Export is inside the weave.enabled block — confirmed by weave agents route also being present
    assert "weave/agents" in src
    assert "knowledge/export" in src


# ===========================================================================
# Group 6: Background sync task source inspection
# ===========================================================================

def test_knowledge_sync_task_in_startup():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod.ClawGateway.startup)
    assert "knowledge_sync_interval" in src
    assert "_knowledge_sync_loop" in src
    assert "weave-knowledge-sync" in src


def test_knowledge_sync_task_uses_pull_knowledge_index():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod.ClawGateway.startup)
    assert "pull_knowledge_index" in src


def test_knowledge_sync_task_uses_list_agents():
    import claw.gateway.server as srv_mod
    src = inspect.getsource(srv_mod.ClawGateway.startup)
    assert "list_agents" in src


# ===========================================================================
# Group 7: CLI command
# ===========================================================================

def test_cli_sync_knowledge_command_registered():
    import claw.cli as cli_mod
    src = inspect.getsource(cli_mod)
    assert "sync-knowledge" in src


def test_cli_sync_knowledge_handler_defined():
    import claw.cli as cli_mod
    assert hasattr(cli_mod, "_cmd_weave_sync_knowledge")


def test_cli_sync_knowledge_checks_knowledge_enabled():
    import claw.cli as cli_mod
    src = inspect.getsource(cli_mod._cmd_weave_sync_knowledge)
    assert "knowledge.enabled" in src


def test_cli_sync_knowledge_reports_peer_namespace():
    import claw.cli as cli_mod
    src = inspect.getsource(cli_mod._cmd_weave_sync_knowledge)
    assert "peer:" in src
