# Knowledge Model — Infinity Claw

## Purpose

The knowledge model defines how information becomes agent-accessible. Getting this right is the difference between an agent that has access to raw files and an agent that understands its workspace.

---

## Current State: Two-Track Context Injection

Infinity Claw makes workspace knowledge available through two complementary tracks:

**Track 1 — Identity/boot files (verbatim, always)**

Eight named files are read whole and injected directly into the system prompt on every turn:

```
AGENTS.md   SOUL.md   IDENTITY.md   USER.md   TOOLS.md
HEARTBEAT.md   BOOT.md   BOOTSTRAP.md
```

These are control structures — agent persona, user profile, tool annotations. They stay verbatim because they are short, authoritative, and always relevant.

**Track 2 — Knowledge index (FTS5, on demand)**

All *other* files in the workspace directory are indexed into a SQLite FTS5 knowledge store. At turn time, the top-K chunks most relevant to the incoming message are retrieved and injected as a `## Relevant Knowledge` section.

```
System prompt
 ├── Agent identity + persona   (AGENTS.md / SOUL.md / IDENTITY.md)
 ├── User profile               (USER.md)
 ├── Tool notes                 (TOOLS.md)
 ├── Runtime metadata           (date, time, host)
 ├── Boot files                 (HEARTBEAT.md / BOOT.md / BOOTSTRAP.md)
 ├── Memory recall              (top-N MemoryNode matches)
 ├── Relevant Knowledge         (top-K FTS5 chunks from workspace)  ← Phase 5
 └── Skills + tools
```

This approach scales: the context window stays bounded regardless of workspace size.

---

## Knowledge Pipeline (Phase 5 — implemented)

```
Workspace directory
        ↓
WorkspaceScanner      ← lists files; excludes identity/boot files + unsupported extensions
        ↓
ingest_file()
  ├── parse_file()    ← read text; strip HTML for .html/.htm
  └── chunk_text()    ← sliding window (configurable chunk_size + overlap)
        ↓
KnowledgeIndex.upsert_many()
  ├── knowledge_chunks  (regular SQLite table: chunk_id, workspace_id, source_file, position, content, fts_rowid)
  └── knowledge_fts     (FTS5 virtual table: content; linked via fts_rowid FK)
        ↓
KnowledgeRetriever.retrieve()
  ├── fts5_query()    ← extract words; join with OR; exclude FTS5 reserved words
  ├── FTS5 MATCH      ← BM25 ranked search (lower/more negative rank = better)
  └── workspace_id filter  ← per-agent isolation in base table
        ↓
KnowledgeInjector.build_block()
        ↓
PromptContext.knowledge_block   ← injected into system prompt
```

---

## Implementation

### Chunk (atomic unit)

```python
@dataclass
class Chunk:
    chunk_id:     str   # UUID, fresh per ingest_file() call
    source_file:  str   # absolute path
    workspace_id: str   # agent_id
    content:      str   # text segment
    position:     int   # chunk index within source file
```

### KnowledgeIndex (SQLite FTS5)

Two-table schema:

- `knowledge_chunks` — canonical metadata row; stores `fts_rowid` FK into FTS5 table
- `knowledge_fts` — FTS5 virtual table (content-only); DELETE requires rowid, hence the FK

Key operations:
- `upsert_many(chunks)` — INSERT into FTS5 first (get rowid), then INSERT into base table
- `clear_source(file, workspace_id)` — fetch rowids, DELETE from FTS5 by rowid, DELETE from base table
- `search(query, workspace_id, top_k)` — FTS5 MATCH → filter by workspace_id → sort by rank

### Configuration

```toml
[knowledge]
enabled      = false   # opt-in; disabled by default
db_path      = ""      # defaults to ~/.claw/knowledge.db
chunk_size   = 500     # characters per chunk
chunk_overlap = 50     # overlap between consecutive chunks
top_k        = 5       # chunks injected per turn
```

---

## Ingestion Triggers

| Trigger | Status | Description |
|---|---|---|
| Startup scan | **Implemented** | On `claw start`, all workspace files are indexed for each agent |
| Manual | **Implemented** | `claw workspace index [--agent ID]` |
| File watcher | Phase 6+ | Auto-reindex on workspace file change |
| Agent write | Phase 6+ | Auto-index when agent writes a file |
| URL fetch | Phase 6+ | Optional indexing of `browser_fetch` responses |

---

## Format Support

| Format | Status | Notes |
|---|---|---|
| Markdown (`.md`) | **Implemented** | Character-based chunking |
| Plaintext (`.txt`, `.rst`) | **Implemented** | Character-based chunking |
| HTML (`.html`, `.htm`) | **Implemented** | Tags stripped via regex before chunking |
| Code (`.py`, `.js`, `.ts`) | **Implemented** | Character-based chunking |
| CSV / JSON | **Implemented** | Character-based chunking |
| PDF | Phase 6+ | Requires `pdfminer`/`pypdf` |
| DOCX | Phase 6+ | Requires `python-docx` |

---

## Retrieval Strategy (Phase 5)

FTS5 BM25 keyword retrieval:
1. Extract words from the user message (≥2 chars, filter FTS5 reserved words)
2. Join as `word1 OR word2 OR ...` FTS5 query
3. Search `knowledge_fts MATCH ?` → ranked by BM25 (more negative = better)
4. Filter by `workspace_id` in base table join
5. Return top-K chunks

**Phase 6+ upgrade path:** Replace FTS5 with cosine similarity over embeddings (OpenAI `text-embedding-3-small` or local model) stored in `sqlite-vec` or AINDY MAS pgvector. The `KnowledgeRetriever` interface is stable — only the index backend changes.

---

## Relationship Extraction (Phase 6+)

Beyond keyword retrieval, future phases will extract explicit relationships between documents:

- **Automatic:** citation links, temporal succession, cross-references to memory nodes
- **LLM-assisted:** `contradicts`, `supports`, `elaborates`, `supersedes`, `references`

These form the knowledge graph traversed during retrieval to expand context beyond direct matches.

---

## Integration with Memory

Memories and knowledge chunks are injected separately but adjacent in the system prompt:

```
 ├── [Memories]   Top-5 recalled memory nodes  (MemoryManager.recall)
 ├── [Knowledge]  Top-K relevant workspace chunks  (KnowledgeRetriever.retrieve)
```

Phase 6+: memory nodes may link to the chunks that prompted their creation (`derived_from`), and retrieval may optionally surface memories alongside chunks.

---

## Non-Goals (Phase 5)

- **OCR on scanned images** — text-based documents only
- **Audio / video transcription** — not in scope
- **Semantic/vector similarity** — FTS5 BM25 only; embedding-based retrieval is Phase 6+
- **Cross-workspace retrieval** — knowledge is scoped per `workspace_id` (agent_id)
- **Real-time file watching** — batch ingestion only (startup + manual); watcher is Phase 6+
