"""Phase 15 — Operational Hardening.

Schema versioning in all three SQLite stores, backup/restore CLI commands,
and expanded claw doctor checks.

33 assertions across 14 pytest-collected functions.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ===========================================================================
# Group 1: Schema versioning — MemorySqliteStore
# ===========================================================================

def test_memory_store_schema_version_table_exists():
    from claw.memory.sqlite_store import MemorySqliteStore
    store = MemorySqliteStore(":memory:")
    conn = store._connect()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    assert row is not None
    store.close()


def test_memory_store_schema_version_is_current():
    from claw.memory.sqlite_store import MemorySqliteStore, SCHEMA_VERSION
    store = MemorySqliteStore(":memory:")
    assert store.schema_version() == SCHEMA_VERSION
    store.close()


def test_memory_store_schema_version_exported():
    from claw.memory import sqlite_store
    assert hasattr(sqlite_store, "SCHEMA_VERSION")
    assert isinstance(sqlite_store.SCHEMA_VERSION, int)
    assert sqlite_store.SCHEMA_VERSION >= 1


# ===========================================================================
# Group 2: Schema versioning — WorkspaceStore
# ===========================================================================

def test_workspace_store_schema_version_table_exists():
    from claw.workspace.store import WorkspaceStore
    store = WorkspaceStore(":memory:")
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    assert row is not None
    store.close()


def test_workspace_store_schema_version_is_current():
    from claw.workspace.store import WorkspaceStore, SCHEMA_VERSION
    store = WorkspaceStore(":memory:")
    assert store.schema_version() == SCHEMA_VERSION
    store.close()


def test_workspace_store_schema_version_exported():
    from claw.workspace import store as ws_module
    assert hasattr(ws_module, "SCHEMA_VERSION")
    assert isinstance(ws_module.SCHEMA_VERSION, int)
    assert ws_module.SCHEMA_VERSION >= 1


# ===========================================================================
# Group 3: Schema versioning — WeaveNodeStore
# ===========================================================================

def test_weave_store_schema_version_table_exists():
    from claw.weave.registry import WeaveNodeStore
    store = WeaveNodeStore(":memory:")
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    assert row is not None
    store.close()


def test_weave_store_schema_version_is_current():
    from claw.weave.registry import WeaveNodeStore, SCHEMA_VERSION
    store = WeaveNodeStore(":memory:")
    assert store.schema_version() == SCHEMA_VERSION
    store.close()


def test_weave_store_schema_version_exported():
    from claw.weave import registry as weave_module
    assert hasattr(weave_module, "SCHEMA_VERSION")
    assert isinstance(weave_module.SCHEMA_VERSION, int)
    assert weave_module.SCHEMA_VERSION >= 1


# ===========================================================================
# Group 4: Backup command
# ===========================================================================

def test_backup_creates_valid_tar_gz(tmp_path):
    from claw.cli import _cmd_backup
    from claw.config.schema import ClawConfig, MemoryConfig, WorkspaceConfig, WeaveConfig
    from claw.memory.sqlite_store import MemorySqliteStore
    from claw.workspace.store import WorkspaceStore
    from claw.weave.registry import WeaveNodeStore

    mem_db = str(tmp_path / "memory.db")
    ws_db = str(tmp_path / "workspace.db")

    MemorySqliteStore(mem_db).close()
    WorkspaceStore(ws_db).close()

    cfg = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=mem_db),
        workspace=WorkspaceConfig(enabled=True, db_path=ws_db),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )

    output = str(tmp_path / "test-backup.tar.gz")
    args = MagicMock(config=None, output=output)

    with patch("claw.config.loader.load_config", return_value=cfg):
        _cmd_backup(args)

    assert Path(output).exists()
    assert tarfile.is_tarfile(output)


def test_backup_manifest_has_expected_fields(tmp_path):
    from claw.cli import _cmd_backup
    from claw.config.schema import ClawConfig, MemoryConfig, WorkspaceConfig, WeaveConfig
    from claw.memory.sqlite_store import MemorySqliteStore, SCHEMA_VERSION as MEM_VER

    mem_db = str(tmp_path / "memory.db")
    MemorySqliteStore(mem_db).close()

    cfg = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=mem_db),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )

    output = str(tmp_path / "backup.tar.gz")
    args = MagicMock(config=None, output=output)

    with patch("claw.config.loader.load_config", return_value=cfg):
        _cmd_backup(args)

    with tarfile.open(output, "r:gz") as tar:
        manifest_f = tar.extractfile("manifest.json")
        assert manifest_f is not None
        manifest = json.loads(manifest_f.read())

    assert "claw_version" in manifest
    assert "timestamp" in manifest
    assert "stores" in manifest
    assert "memory" in manifest["stores"]
    assert manifest["stores"]["memory"]["schema_version"] == MEM_VER


def test_backup_skips_disabled_stores(tmp_path):
    from claw.cli import _cmd_backup
    from claw.config.schema import ClawConfig, MemoryConfig, WorkspaceConfig, WeaveConfig
    from claw.memory.sqlite_store import MemorySqliteStore

    mem_db = str(tmp_path / "memory.db")
    MemorySqliteStore(mem_db).close()

    cfg = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=mem_db),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )

    output = str(tmp_path / "backup.tar.gz")
    args = MagicMock(config=None, output=output)

    with patch("claw.config.loader.load_config", return_value=cfg):
        _cmd_backup(args)

    with tarfile.open(output, "r:gz") as tar:
        names = tar.getnames()

    assert "memory.db" in names
    assert "workspace.db" not in names
    assert "weave.db" not in names


# ===========================================================================
# Group 5: Restore command
# ===========================================================================

def test_restore_roundtrip(tmp_path):
    from claw.cli import _cmd_backup, _cmd_restore
    from claw.config.schema import ClawConfig, MemoryConfig, WorkspaceConfig, WeaveConfig
    from claw.memory.sqlite_store import MemorySqliteStore

    src_db = str(tmp_path / "src" / "memory.db")
    Path(src_db).parent.mkdir(parents=True)
    store = MemorySqliteStore(src_db)
    store.close()

    cfg_src = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=src_db),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path / "src"),
    )

    archive = str(tmp_path / "backup.tar.gz")
    with patch("claw.config.loader.load_config", return_value=cfg_src):
        _cmd_backup(MagicMock(config=None, output=archive))

    dst_db = str(tmp_path / "dst" / "memory.db")
    cfg_dst = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=dst_db),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path / "dst"),
    )

    with patch("claw.config.loader.load_config", return_value=cfg_dst):
        _cmd_restore(MagicMock(config=None, archive=archive))

    assert Path(dst_db).exists()
    restored = MemorySqliteStore(dst_db)
    assert restored.schema_version() >= 1
    restored.close()


def test_restore_fails_on_missing_archive(tmp_path):
    import pytest
    from claw.cli import _cmd_restore
    from claw.config.schema import ClawConfig

    cfg = ClawConfig(state_dir=str(tmp_path))
    args = MagicMock(config=None, archive=str(tmp_path / "nonexistent.tar.gz"))

    with patch("claw.config.loader.load_config", return_value=cfg):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_restore(args)
    assert exc_info.value.code == 1


def test_restore_fails_on_schema_mismatch(tmp_path):
    from claw.cli import _cmd_restore
    from claw.config.schema import ClawConfig, MemoryConfig, WorkspaceConfig, WeaveConfig

    manifest = {
        "claw_version": "0.0.1",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "stores": {"memory": {"schema_version": 999}},
    }
    archive = str(tmp_path / "mismatch.tar.gz")
    with tempfile.TemporaryDirectory() as tmpdir:
        mf = Path(tmpdir) / "manifest.json"
        mf.write_text(json.dumps(manifest))
        dummy_db = Path(tmpdir) / "memory.db"
        conn = sqlite3.connect(str(dummy_db))
        conn.close()
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(mf, arcname="manifest.json")
            tar.add(dummy_db, arcname="memory.db")

    cfg = ClawConfig(
        memory=MemoryConfig(enabled=True, db_path=str(tmp_path / "memory.db")),
        state_dir=str(tmp_path),
    )

    with patch("claw.config.loader.load_config", return_value=cfg):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            _cmd_restore(MagicMock(config=None, archive=archive))
    assert exc_info.value.code == 1


# ===========================================================================
# Group 6: Doctor helper functions
# ===========================================================================

def test_db_integrity_ok_on_valid_db(tmp_path):
    from claw.cli import _db_integrity_ok
    from claw.memory.sqlite_store import MemorySqliteStore

    db = str(tmp_path / "memory.db")
    MemorySqliteStore(db).close()
    assert _db_integrity_ok(db) is True


def test_db_integrity_ok_returns_false_on_missing_file(tmp_path):
    from claw.cli import _db_integrity_ok
    assert _db_integrity_ok(str(tmp_path / "nonexistent.db")) is False


def test_db_integrity_ok_exported():
    import claw.cli as cli_module
    assert hasattr(cli_module, "_db_integrity_ok")
    assert callable(cli_module._db_integrity_ok)


def test_config_consistency_warns_on_aindy_backend_without_aindy(tmp_path):
    from claw.cli import _check_config_consistency
    from claw.config.schema import ClawConfig, AINDYConfig, MemoryConfig, WorkspaceConfig, WeaveConfig

    cfg = ClawConfig(
        aindy=AINDYConfig(enabled=False, memory_backend="aindy"),
        memory=MemoryConfig(enabled=False),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )
    warnings = _check_config_consistency(cfg)
    assert any("memory_backend" in w for w in warnings)


def test_config_consistency_no_backend_warning_for_local(tmp_path):
    from claw.cli import _check_config_consistency
    from claw.config.schema import ClawConfig, AINDYConfig, MemoryConfig, WorkspaceConfig, WeaveConfig

    cfg = ClawConfig(
        aindy=AINDYConfig(enabled=False, memory_backend="local"),
        memory=MemoryConfig(enabled=False),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )
    warnings = _check_config_consistency(cfg)
    assert not any("memory_backend" in w for w in warnings)


def test_config_consistency_warns_on_inline_secret(tmp_path):
    from claw.cli import _check_config_consistency
    from claw.config.schema import ClawConfig, AINDYConfig, GatewayConfig, MemoryConfig, WorkspaceConfig, WeaveConfig

    cfg = ClawConfig(
        gateway=GatewayConfig(token="sk-ant-api03-realkey123"),
        aindy=AINDYConfig(enabled=False),
        memory=MemoryConfig(enabled=False),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )
    warnings = _check_config_consistency(cfg)
    assert any("gateway.token" in w for w in warnings)


def test_config_consistency_no_warning_for_env_var_ref(tmp_path):
    from claw.cli import _check_config_consistency
    from claw.config.schema import ClawConfig, AINDYConfig, GatewayConfig, MemoryConfig, WorkspaceConfig, WeaveConfig

    cfg = ClawConfig(
        gateway=GatewayConfig(token="$CLAW_GATEWAY_TOKEN"),
        aindy=AINDYConfig(enabled=False),
        memory=MemoryConfig(enabled=False),
        workspace=WorkspaceConfig(enabled=False),
        weave=WeaveConfig(enabled=False),
        state_dir=str(tmp_path),
    )
    warnings = _check_config_consistency(cfg)
    assert not any("gateway.token" in w for w in warnings)
