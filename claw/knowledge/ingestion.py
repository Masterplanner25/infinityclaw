"""Knowledge ingestion — parse workspace files into retrievable chunks."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SUPPORTED_EXTENSIONS = {
    ".md", ".txt", ".rst",
    ".html", ".htm",
    ".py", ".js", ".ts",
    ".json", ".csv",
}

# FTS5 stopwords that would break OR-joined queries
_FTS5_STOPWORDS = {"or", "and", "not", "near"}


@dataclass
class Chunk:
    """Atomic unit of indexed knowledge."""
    chunk_id: str
    source_file: str
    workspace_id: str
    content: str
    position: int  # chunk index within source file


def parse_file(path: Path) -> Optional[str]:
    """Read a file and extract its text. Returns None for unsupported types."""
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    if path.suffix.lower() in {".html", ".htm"}:
        text = _strip_html(text)
    return text or None


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split *text* into overlapping fixed-size chunks."""
    if not text:
        return []
    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start:start + chunk_size].strip()
        if piece:
            chunks.append(piece)
    return chunks


def ingest_file(
    path: Path,
    workspace_id: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """Parse and chunk a workspace file into Chunk objects."""
    text = parse_file(path)
    if text is None:
        return []
    texts = chunk_text(text, chunk_size, chunk_overlap)
    return [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            source_file=str(path),
            workspace_id=workspace_id,
            content=c,
            position=i,
        )
        for i, c in enumerate(texts)
    ]


def fts5_query(text: str) -> str:
    """Build a safe FTS5 OR query from arbitrary text."""
    words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]{2,}", text)]
    words = [w for w in words if w not in _FTS5_STOPWORDS][:20]
    return " OR ".join(words) if words else ""


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
