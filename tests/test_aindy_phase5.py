"""AINDY Phase 5 milestone test — Knowledge Layer.

Tests (no real server or AINDY needed):
- KnowledgeConfig present in ClawConfig with correct defaults
- parse_file() reads supported formats and rejects unsupported ones
- chunk_text() splits text with overlap
- ingest_file() end-to-end ingestion pipeline
- KnowledgeIndex (:memory:) — upsert_many, search, clear_source, count
- WorkspaceScanner excludes identity/boot files
- KnowledgeRetriever.retrieve() returns ranked chunks (async)
- KnowledgeInjector.build_block() formats prompt section
- PromptContext.knowledge_block field is present
- SystemPromptBuilder injects knowledge_block between memories and skills
- ClawGateway initializes knowledge subsystem when enabled
- CLI `workspace index` exits with error when knowledge is disabled

Run:  python tests/test_aindy_phase5.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[??]")
    print(f"  {icon}  {name}" + (f" -- {note}" if note else ""))


# ------------------------------------------------------------------
# 1. KnowledgeConfig in ClawConfig
# ------------------------------------------------------------------

def test_knowledge_config() -> None:
    print("\n== KnowledgeConfig ==")
    try:
        from claw.config.schema import ClawConfig, KnowledgeConfig

        cfg = ClawConfig()
        assert hasattr(cfg, "knowledge"), "ClawConfig missing .knowledge"
        assert isinstance(cfg.knowledge, KnowledgeConfig)
        check("ClawConfig.knowledge field present", PASS)

        assert cfg.knowledge.enabled is False
        assert cfg.knowledge.db_path == ""
        assert cfg.knowledge.chunk_size == 500
        assert cfg.knowledge.chunk_overlap == 50
        assert cfg.knowledge.top_k == 5
        check("KnowledgeConfig defaults", PASS)

        custom = KnowledgeConfig(enabled=True, chunk_size=300, top_k=10)
        assert custom.enabled is True and custom.chunk_size == 300 and custom.top_k == 10
        check("KnowledgeConfig custom values", PASS)

    except Exception as exc:
        check("KnowledgeConfig", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 2. parse_file — format support
# ------------------------------------------------------------------

def test_parse_file() -> None:
    print("\n== parse_file() ==")
    try:
        from claw.knowledge.ingestion import parse_file

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            md = d / "notes.md"
            md.write_text("# Title\n\nSome content here.", encoding="utf-8")
            text = parse_file(md)
            assert text and "Some content here" in text
            check("parse_file() reads .md", PASS)

            txt = d / "plain.txt"
            txt.write_text("plain text content", encoding="utf-8")
            assert parse_file(txt) == "plain text content"
            check("parse_file() reads .txt", PASS)

            html = d / "page.html"
            html.write_text("<html><body><p>Hello world</p></body></html>", encoding="utf-8")
            result = parse_file(html)
            assert result and "Hello world" in result and "<html" not in result
            check("parse_file() strips HTML", PASS)

            empty = d / "empty.md"
            empty.write_text("   ", encoding="utf-8")
            assert parse_file(empty) is None
            check("parse_file() returns None for empty file", PASS)

            unsupported = d / "image.png"
            unsupported.write_bytes(b"\x89PNG")
            assert parse_file(unsupported) is None
            check("parse_file() returns None for unsupported extension", PASS)

    except Exception as exc:
        check("parse_file", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 3. chunk_text — splitting and overlap
# ------------------------------------------------------------------

def test_chunk_text() -> None:
    print("\n== chunk_text() ==")
    try:
        from claw.knowledge.ingestion import chunk_text

        # Short text produces one chunk
        chunks = chunk_text("hello world", chunk_size=500)
        assert len(chunks) == 1 and chunks[0] == "hello world"
        check("Short text -> single chunk", PASS)

        # Longer text with overlap
        text = "A" * 100
        chunks = chunk_text(text, chunk_size=40, overlap=10)
        assert len(chunks) >= 3, f"expected >=3 chunks, got {len(chunks)}"
        assert len(chunks[0]) == 40
        check("Chunking with overlap", PASS, f"{len(chunks)} chunks")

        # Empty text
        assert chunk_text("") == []
        check("Empty text -> no chunks", PASS)

        # Overlap >= chunk_size doesn't loop forever
        chunks2 = chunk_text("x" * 50, chunk_size=10, overlap=10)
        assert len(chunks2) <= 60, "overlap=chunk_size produced too many chunks"
        check("overlap >= chunk_size guard", PASS)

    except Exception as exc:
        check("chunk_text", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 4. ingest_file — end-to-end pipeline
# ------------------------------------------------------------------

def test_ingest_file() -> None:
    print("\n== ingest_file() ==")
    try:
        from claw.knowledge.ingestion import ingest_file, Chunk

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            src = d / "reference.md"
            long_text = "Python is a programming language. " * 50  # ~1650 chars
            src.write_text(long_text, encoding="utf-8")

            chunks = ingest_file(src, workspace_id="main", chunk_size=200, chunk_overlap=20)
            assert len(chunks) > 1, f"expected multiple chunks, got {len(chunks)}"
            for i, c in enumerate(chunks):
                assert c.workspace_id == "main"
                assert c.source_file == str(src)
                assert c.position == i
                assert c.chunk_id  # non-empty UUID
                assert c.content
            check("ingest_file() produces multiple chunks", PASS, f"{len(chunks)} chunks")

            # Unsupported format returns empty
            binary = d / "data.bin"
            binary.write_bytes(b"\x00\x01\x02")
            assert ingest_file(binary, "main") == []
            check("ingest_file() returns [] for unsupported format", PASS)

            # Each call to ingest_file generates fresh chunk_ids
            chunks2 = ingest_file(src, workspace_id="main", chunk_size=200, chunk_overlap=20)
            ids1 = {c.chunk_id for c in chunks}
            ids2 = {c.chunk_id for c in chunks2}
            assert not ids1 & ids2, "chunk_ids should be fresh UUIDs each call"
            check("ingest_file() generates unique chunk_ids each call", PASS)

    except Exception as exc:
        check("ingest_file", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 5. KnowledgeIndex — store, search, clear, count
# ------------------------------------------------------------------

def test_knowledge_index() -> None:
    print("\n== KnowledgeIndex ==")
    try:
        from claw.knowledge.index import KnowledgeIndex
        from claw.knowledge.ingestion import Chunk
        import uuid

        idx = KnowledgeIndex(":memory:")

        def _chunk(content: str, workspace: str = "main", src: str = "notes.md") -> Chunk:
            return Chunk(
                chunk_id=str(uuid.uuid4()),
                source_file=src,
                workspace_id=workspace,
                content=content,
                position=0,
            )

        # Insert and count
        c1 = _chunk("Python is a high-level programming language.")
        c2 = _chunk("FastAPI is a modern web framework for Python.")
        c3 = _chunk("SQLite is a self-contained database engine.")
        idx.upsert_many([c1, c2, c3])
        assert idx.count("main") == 3
        check("upsert_many() + count()", PASS, "3 chunks")

        # Search — should find Python-related chunks
        results_py = idx.search("python programming", "main", top_k=5)
        ids = {r.chunk_id for r in results_py}
        assert c1.chunk_id in ids or c2.chunk_id in ids, \
            f"expected Python chunks in results, got ids={ids}"
        check("search() finds relevant chunks", PASS, f"{len(results_py)} results")

        # Workspace isolation — coder has no chunks
        results_coder = idx.search("python", "coder", top_k=5)
        assert results_coder == []
        check("Workspace isolation — empty for unknown workspace", PASS)

        # Add coder chunks
        c4 = _chunk("Go is statically typed and compiled.", workspace="coder", src="go.md")
        idx.upsert_many([c4])
        assert idx.count("coder") == 1
        assert idx.count("main") == 3  # unchanged
        check("Per-workspace chunk counts", PASS)

        # clear_source
        idx.clear_source("notes.md", "main")
        assert idx.count("main") == 0
        results_after = idx.search("python", "main", top_k=5)
        assert results_after == []
        check("clear_source() removes chunks and FTS entries", PASS)

        # clear_workspace
        idx.upsert_many([_chunk("Another chunk", workspace="main")])
        idx.clear_workspace("main")
        assert idx.count("main") == 0
        check("clear_workspace() removes all chunks for workspace", PASS)

        # Empty query returns no results (no crash)
        assert idx.search("", "main", top_k=5) == []
        check("Empty query returns []", PASS)

        idx.close()

    except Exception as exc:
        check("KnowledgeIndex", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 6. WorkspaceScanner — excludes identity files
# ------------------------------------------------------------------

def test_workspace_scanner() -> None:
    print("\n== WorkspaceScanner ==")
    try:
        from claw.knowledge.scanner import WorkspaceScanner
        from claw.workspace.bootstrapper import ALL_WORKSPACE_FILES

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            # Write identity/boot files (should be excluded)
            for name in ALL_WORKSPACE_FILES:
                (d / name).write_text(f"# {name}", encoding="utf-8")

            # Write knowledge files (should be included)
            (d / "project-notes.md").write_text("# Notes\nSome content", encoding="utf-8")
            (d / "reference.txt").write_text("reference text", encoding="utf-8")

            # Write unsupported file (should be excluded by extension)
            (d / "data.db").write_bytes(b"\x00\x01")

            scanner = WorkspaceScanner()
            found = scanner.scan(d)
            names = {p.name for p in found}

            # Identity files excluded
            for name in ALL_WORKSPACE_FILES:
                assert name not in names, f"{name} should be excluded"
            check("Identity/boot files excluded from scan", PASS)

            # Knowledge files included
            assert "project-notes.md" in names
            assert "reference.txt" in names
            check("Knowledge files included in scan", PASS, f"{len(found)} files")

            # Unsupported extension excluded
            assert "data.db" not in names
            check("Unsupported extension excluded", PASS)

            # Non-existent dir returns []
            assert scanner.scan(d / "nonexistent") == []
            check("Non-existent dir returns []", PASS)

    except Exception as exc:
        check("WorkspaceScanner", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 7. KnowledgeRetriever — async wrapper
# ------------------------------------------------------------------

async def test_knowledge_retriever() -> None:
    print("\n== KnowledgeRetriever ==")
    try:
        from claw.knowledge.index import KnowledgeIndex
        from claw.knowledge.retrieval import KnowledgeRetriever
        from claw.knowledge.ingestion import Chunk
        import uuid

        idx = KnowledgeIndex(":memory:")
        chunks = [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                source_file="docs.md",
                workspace_id="main",
                content="Claude is an AI assistant made by Anthropic.",
                position=0,
            ),
            Chunk(
                chunk_id=str(uuid.uuid4()),
                source_file="docs.md",
                workspace_id="main",
                content="FastAPI makes building APIs simple and fast.",
                position=1,
            ),
        ]
        idx.upsert_many(chunks)

        retriever = KnowledgeRetriever(idx, top_k=3)
        results_list = await retriever.retrieve("Anthropic AI assistant", "main")
        assert len(results_list) >= 1
        assert any("Anthropic" in r.content for r in results_list)
        check("retrieve() returns relevant chunks async", PASS, f"{len(results_list)} results")

        # Empty workspace returns []
        empty = await retriever.retrieve("anything", "nobody")
        assert empty == []
        check("retrieve() returns [] for unknown workspace", PASS)

        idx.close()

    except Exception as exc:
        check("KnowledgeRetriever", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 8. KnowledgeInjector — prompt block formatting
# ------------------------------------------------------------------

def test_knowledge_injector() -> None:
    print("\n== KnowledgeInjector ==")
    try:
        from claw.knowledge.injector import KnowledgeInjector
        from claw.knowledge.ingestion import Chunk
        import uuid

        injector = KnowledgeInjector()

        chunks = [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                source_file="/ws/notes.md",
                workspace_id="main",
                content="This is the first relevant chunk.",
                position=0,
            ),
            Chunk(
                chunk_id=str(uuid.uuid4()),
                source_file="/ws/reference.txt",
                workspace_id="main",
                content="This is the second relevant chunk.",
                position=1,
            ),
        ]

        block = injector.build_block(chunks)
        assert "Relevant Knowledge" in block
        assert "notes.md" in block
        assert "reference.txt" in block
        assert "first relevant chunk" in block
        assert "second relevant chunk" in block
        check("build_block() formats knowledge section", PASS)

        # Empty list returns empty string
        assert injector.build_block([]) == ""
        check("build_block() returns empty string for no chunks", PASS)

    except Exception as exc:
        check("KnowledgeInjector", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 9. PromptContext.knowledge_block field
# ------------------------------------------------------------------

def test_prompt_context_knowledge_block() -> None:
    print("\n== PromptContext.knowledge_block ==")
    try:
        from claw.agents.prompt import PromptContext

        ctx = PromptContext(agent_id="main", agent_name="Claw")
        assert hasattr(ctx, "knowledge_block"), "PromptContext missing knowledge_block"
        assert ctx.knowledge_block == ""
        check("PromptContext.knowledge_block defaults to empty string", PASS)

        ctx2 = PromptContext(
            agent_id="main",
            agent_name="Claw",
            knowledge_block="## Relevant Knowledge\n\nSome content.",
        )
        assert ctx2.knowledge_block == "## Relevant Knowledge\n\nSome content."
        check("PromptContext.knowledge_block accepts custom value", PASS)

    except Exception as exc:
        check("PromptContext.knowledge_block", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 10. SystemPromptBuilder injects knowledge_block
# ------------------------------------------------------------------

def test_system_prompt_builder_knowledge() -> None:
    print("\n== SystemPromptBuilder knowledge injection ==")
    try:
        from claw.agents.prompt import PromptContext, SystemPromptBuilder

        builder = SystemPromptBuilder()

        # knowledge_block injected when present
        ctx = PromptContext(
            agent_id="main",
            agent_name="Claw",
            memories_block="## Relevant Memories\n- prefers Python",
            knowledge_block="## Relevant Knowledge\n\n**[notes.md]**\nKey fact here.",
            skills_block="## Skills\n- skill1",
        )
        prompt = builder.build(ctx)
        assert "Relevant Knowledge" in prompt
        assert "Key fact here" in prompt
        check("knowledge_block appears in built prompt", PASS)

        # Appears between memories and skills
        mem_pos = prompt.find("Relevant Memories")
        knowledge_pos = prompt.find("Relevant Knowledge")
        skills_pos = prompt.find("## Skills")
        assert mem_pos < knowledge_pos < skills_pos, (
            f"expected memories < knowledge < skills, "
            f"got {mem_pos} < {knowledge_pos} < {skills_pos}"
        )
        check("knowledge_block position: after memories, before skills", PASS)

        # Absent when empty
        ctx_no_knowledge = PromptContext(agent_id="main", agent_name="Claw")
        prompt2 = builder.build(ctx_no_knowledge)
        assert "Relevant Knowledge" not in prompt2
        check("Empty knowledge_block not injected", PASS)

    except Exception as exc:
        check("SystemPromptBuilder knowledge", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 11. ClawGateway initializes knowledge subsystem
# ------------------------------------------------------------------

def test_gateway_knowledge_init() -> None:
    print("\n== ClawGateway knowledge subsystem ==")
    try:
        from claw.config.schema import ClawConfig, CredentialConfig, MemoryConfig, KnowledgeConfig
        from claw.gateway.server import ClawGateway
        from claw.knowledge.index import KnowledgeIndex
        from claw.knowledge.retrieval import KnowledgeRetriever
        from claw.knowledge.injector import KnowledgeInjector

        def _cfg(knowledge_enabled: bool) -> ClawConfig:
            cfg = ClawConfig()
            cfg.credentials = [CredentialConfig(
                id="test", provider="anthropic", api_key="sk-ant-test-fake"
            )]
            cfg.memory = MemoryConfig(enabled=True, db_path=":memory:")
            cfg.knowledge = KnowledgeConfig(
                enabled=knowledge_enabled,
                db_path=":memory:",
            )
            return cfg

        # Disabled (default): knowledge attributes are None
        gw_off = ClawGateway(_cfg(False))
        assert gw_off.knowledge_index is None
        assert gw_off.knowledge_retriever is None
        assert gw_off.knowledge_injector is None
        check("knowledge disabled -> all knowledge attrs None", PASS)

        # Enabled: knowledge attributes are initialized
        gw_on = ClawGateway(_cfg(True))
        assert isinstance(gw_on.knowledge_index, KnowledgeIndex)
        assert isinstance(gw_on.knowledge_retriever, KnowledgeRetriever)
        assert isinstance(gw_on.knowledge_injector, KnowledgeInjector)
        check("knowledge enabled -> index, retriever, injector initialized", PASS)

    except Exception as exc:
        check("ClawGateway knowledge init", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# 12. CLI workspace index — exits when knowledge disabled
# ------------------------------------------------------------------

def test_cli_workspace_index_disabled() -> None:
    print("\n== CLI workspace index (knowledge disabled) ==")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "claw", "--config", "claw.toml", "workspace", "index"],
            capture_output=True, text=True, timeout=15,
        )
        # Should fail with a message about knowledge being disabled
        output = r.stdout + r.stderr
        assert r.returncode != 0, f"expected non-zero exit, got 0; output={output[:200]}"
        assert "disabled" in output.lower() or "knowledge" in output.lower(), \
            f"expected 'disabled' in output: {output[:200]}"
        check("workspace index exits with error when knowledge disabled", PASS)

    except Exception as exc:
        check("CLI workspace index disabled", FAIL, str(exc))
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def run_async_tests() -> None:
    await test_knowledge_retriever()


def main() -> None:
    print("=" * 60)
    print("  Claw AINDY Phase 5 Milestone Test — Knowledge Layer")
    print("=" * 60)

    test_knowledge_config()
    test_parse_file()
    test_chunk_text()
    test_ingest_file()
    test_knowledge_index()
    test_workspace_scanner()
    asyncio.run(run_async_tests())
    test_knowledge_injector()
    test_prompt_context_knowledge_block()
    test_system_prompt_builder_knowledge()
    test_gateway_knowledge_init()
    test_cli_workspace_index_disabled()

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
