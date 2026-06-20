"""KnowledgeIndex — SQLite FTS5 backed knowledge store."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from .ingestion import Chunk, fts5_query

logger = logging.getLogger(__name__)


class KnowledgeIndex:
    """SQLite knowledge index using FTS5 for full-text retrieval.

    Two tables:
    - knowledge_chunks: canonical metadata (rowid, chunk_id, workspace_id, source_file, …)
    - knowledge_fts:    FTS5 virtual table (content only); linked via fts_rowid column
    """

    def __init__(self, db_path: str) -> None:
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            p = Path(db_path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(p), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id     TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_file  TEXT NOT NULL,
                position     INTEGER NOT NULL,
                content      TEXT NOT NULL,
                fts_rowid    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_kc_workspace
                ON knowledge_chunks(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_kc_source
                ON knowledge_chunks(workspace_id, source_file);
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(content);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_many(self, chunks: list[Chunk]) -> None:
        """Insert *chunks* into the index (caller should call clear_source first)."""
        for chunk in chunks:
            cursor = self._conn.execute(
                "INSERT INTO knowledge_fts(content) VALUES (?)", (chunk.content,)
            )
            fts_rowid = cursor.lastrowid
            self._conn.execute(
                "INSERT INTO knowledge_chunks "
                "(chunk_id, workspace_id, source_file, position, content, fts_rowid) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id, chunk.workspace_id, chunk.source_file,
                    chunk.position, chunk.content, fts_rowid,
                ),
            )
        self._conn.commit()

    def clear_source(self, source_file: str, workspace_id: str) -> None:
        """Remove all chunks for *source_file* in *workspace_id*."""
        rows = self._conn.execute(
            "SELECT fts_rowid FROM knowledge_chunks "
            "WHERE source_file = ? AND workspace_id = ?",
            (source_file, workspace_id),
        ).fetchall()
        for (fts_rowid,) in rows:
            if fts_rowid is not None:
                self._conn.execute(
                    "DELETE FROM knowledge_fts WHERE rowid = ?", (fts_rowid,)
                )
        self._conn.execute(
            "DELETE FROM knowledge_chunks WHERE source_file = ? AND workspace_id = ?",
            (source_file, workspace_id),
        )
        self._conn.commit()

    def clear_workspace(self, workspace_id: str) -> None:
        """Remove all chunks for *workspace_id*."""
        rows = self._conn.execute(
            "SELECT fts_rowid FROM knowledge_chunks WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        for (fts_rowid,) in rows:
            if fts_rowid is not None:
                self._conn.execute(
                    "DELETE FROM knowledge_fts WHERE rowid = ?", (fts_rowid,)
                )
        self._conn.execute(
            "DELETE FROM knowledge_chunks WHERE workspace_id = ?", (workspace_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(self, query: str, workspace_id: str, top_k: int = 5) -> list[Chunk]:
        """Return top-K relevant chunks for *query* in *workspace_id*."""
        safe_q = fts5_query(query)
        if not safe_q:
            return []

        try:
            fts_rows = self._conn.execute(
                "SELECT rowid, rank FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe_q, top_k * 3),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("[knowledge] FTS search failed: %s", exc)
            return []

        if not fts_rows:
            return []

        fts_rowid_rank: dict[int, float] = {rowid: rank for rowid, rank in fts_rows}
        placeholders = ",".join("?" * len(fts_rowid_rank))
        kc_rows = self._conn.execute(
            f"SELECT chunk_id, workspace_id, source_file, position, content, fts_rowid "
            f"FROM knowledge_chunks "
            f"WHERE fts_rowid IN ({placeholders}) AND workspace_id = ? "
            f"LIMIT ?",
            [*fts_rowid_rank.keys(), workspace_id, top_k],
        ).fetchall()

        kc_rows.sort(key=lambda r: fts_rowid_rank.get(r[5], 0))

        return [
            Chunk(
                chunk_id=r[0],
                workspace_id=r[1],
                source_file=r[2],
                position=r[3],
                content=r[4],
            )
            for r in kc_rows
        ]

    def count(self, workspace_id: str) -> int:
        """Total chunk count for *workspace_id*."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
