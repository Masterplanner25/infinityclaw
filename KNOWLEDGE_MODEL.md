# Knowledge Model — Infinity Claw

## Purpose

The knowledge model defines how information becomes agent-accessible. Getting this right is the difference between an agent that has access to raw files and an agent that understands its workspace.

---

## Current State: Direct Injection

Today, Infinity Claw makes workspace knowledge available through two mechanisms:

**1. File injection (workspace documents)**

At the start of every turn, files in `~/.claw/agents/{agent_id}/workspace/` are read and appended to the system prompt. The agent sees the raw file content verbatim.

```
System prompt
 ├── Agent identity + persona
 ├── Date / context
 ├── Memory recall (top-N semantic matches)
 ├── Workspace files (verbatim, all files)
 └── Available skills + tools
```

**2. Memory recall (structured)**

At turn start, `MemoryManager.recall(query)` performs a semantic search over the agent's memory nodes and injects the top matches as structured context. Memory nodes were created by previous turns.

**Limitation of this approach:** As the workspace grows, verbatim injection becomes impractical. A workspace with 50 documents fills the context window before the conversation begins. This is the problem the knowledge layer solves.

---

## Phase 5+: Knowledge Pipeline

The knowledge layer sits between workspace files and agent context injection. Rather than injecting everything verbatim, it indexes content and retrieves only what is relevant to the current turn.

```
File / Asset / URL
        ↓
   Ingestion
        ↓
   Parsing          ← extract text from PDF, DOCX, HTML, code, etc.
        ↓
   Chunking         ← split into retrievable segments (size + overlap configurable)
        ↓
   Embedding        ← vector representation via embedding model
        ↓
   Index            ← stored in AINDY MAS (Postgres + pgvector) or local vector store
        ↓
   Retrieval        ← semantic search at turn time
        ↓
   Agent Context    ← only relevant chunks injected into system prompt
```

---

## Knowledge Objects

### Document Chunk

The atomic unit of indexed knowledge:

```
Chunk
 ├── id           (UUID)
 ├── document_id  (parent document)
 ├── workspace_id (owning workspace)
 ├── content      (text segment)
 ├── embedding    (float vector)
 ├── position     (start/end byte offset in source)
 ├── metadata     (page, section, heading, etc.)
 └── indexed_at
```

### Knowledge Index

The index is the searchable store of all chunks for a workspace. Two index backends are planned:

| Backend | Storage | Use case |
|---|---|---|
| AINDY MAS | Postgres + pgvector | Production; shared across Weave nodes |
| Local | SQLite + sqlite-vec | Self-contained; no external dependencies |

---

## Retrieval Strategy

At turn time, the retrieval pipeline:

1. Embeds the incoming user message (or the last N turns as query)
2. Runs cosine similarity search against the workspace's chunk index
3. Optionally traverses the relationship graph from matched chunks (find linked documents, related memories)
4. Assembles the top-K chunks into a context block
5. Injects the context block into the system prompt in place of verbatim files

```python
# Planned interface
context = await knowledge_index.retrieve(
    query=turn_text,
    workspace_id=workspace_id,
    top_k=10,
    include_relationships=True,
)
```

---

## Ingestion Triggers

Documents enter the knowledge pipeline through:

| Trigger | Description |
|---|---|
| Startup scan | On `claw start`, new/changed files in the workspace directory are ingested |
| Manual | `claw workspace index` CLI command |
| Watch mode | File watcher (Phase 5+) re-indexes changed files automatically |
| Agent write | When an agent writes a file to the workspace, it is auto-indexed |
| URL fetch | When `browser_fetch` returns content, it can optionally be indexed into the workspace |

---

## Relationship Extraction

Beyond pure vector similarity, the knowledge model extracts explicit relationships between documents:

**Automatic (Phase 5+):**
- Citation links (`Document A mentions Document B by name`)
- Temporal succession (`Document B updates or supersedes Document A`)
- Cross-reference (`Memory node derived from Document C`)

**LLM-assisted (Phase 6+):**
- Semantic relationships extracted by a lightweight extraction agent
- `contradicts`, `supports`, `elaborates`, `supersedes`, `references`

These relationships form the knowledge graph traversed during retrieval.

---

## Integration with Memory

Memories and knowledge chunks are separate but linked:

- A memory node can be linked to the chunk(s) that prompted its creation (`derived_from`)
- Retrieval can optionally include memories alongside chunks
- The injection prompt block merges both: "what the agent knows (memories)" + "what the workspace contains (chunks)"

```
Agent System Prompt
 ├── Agent identity
 ├── [Memories] Top-5 recalled memory nodes
 ├── [Knowledge] Top-10 relevant workspace chunks
 └── [Skills + tools]
```

---

## Format Support (Planned)

| Format | Parser | Notes |
|---|---|---|
| Markdown | Built-in | Native; headings used as chunk boundaries |
| Plaintext | Built-in | Character-based chunking |
| PDF | `pdfminer` / `pypdf` | Text extraction; no OCR initially |
| HTML | `beautifulsoup4` | Stripped to text |
| Code | Language-aware | Functions and classes as chunk boundaries |
| DOCX | `python-docx` | Paragraph-based chunking |
| CSV / JSON | Structured | Record-based chunking |

---

## Non-Goals

- **OCR on scanned images** — not in scope; text-based documents only
- **Audio / video transcription** — not in scope initially
- **Real-time streaming ingestion** — batch ingestion only (startup + manual trigger); streaming indexing is a future capability
- **Cross-workspace retrieval** — knowledge is scoped per workspace; agents cannot retrieve from other workspaces
