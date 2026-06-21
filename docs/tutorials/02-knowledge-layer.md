# Tutorial: Knowledge Layer

This tutorial sets up the knowledge layer — automatic document indexing and retrieval so your agent can answer questions about files you put in its workspace.

**What you'll build:**
- An agent workspace with indexed documents
- FTS5-backed semantic retrieval injected into every turn
- Auto-reindexing when files change

---

## Step 1 — Enable the knowledge layer

In `claw.toml`:

```toml
[knowledge]
enabled    = true
top_k      = 5      # chunks returned per turn (default: 5)
chunk_size = 500    # characters per chunk (default: 500)
overlap    = 50     # character overlap between chunks (default: 50)
```

Restart Claw after enabling. The knowledge SQLite database is created at `~/.claw/knowledge.db` on first startup.

---

## Step 2 — Add files to the agent workspace

The workspace directory for an agent is at `<state_dir>/agents/<agent_id>/workspace/`. By default:

```
~/.claw/agents/main/workspace/
```

Drop any supported files there:

```powershell
# Copy project docs to the agent workspace
Copy-Item "C:\myproject\README.md"  "$env:USERPROFILE\.claw\agents\main\workspace\"
Copy-Item "C:\myproject\ARCHITECTURE.md" "$env:USERPROFILE\.claw\agents\main\workspace\"
Copy-Item "C:\myproject\API.md" "$env:USERPROFILE\.claw\agents\main\workspace\"
```

**Supported file types:** `.md`, `.txt`, `.html`, `.py`, `.js`, `.ts`, `.go`, `.rs`, `.csv`

Files are scanned from the top level only (non-recursive). Subdirectories are not indexed.

Identity/boot files (`identity.md`, `boot.md`, etc.) are excluded from indexing — they are loaded into the system prompt directly.

---

## Step 3 — Index the workspace

Files are indexed automatically on startup. You can also trigger a reindex manually:

```powershell
# Reindex all agents
venv\Scripts\python.exe -m claw workspace index

# Reindex a specific agent
venv\Scripts\python.exe -m claw workspace index --agent main
```

The indexer:
1. Reads each file and splits it into overlapping chunks
2. Assigns each chunk a UUID
3. Writes chunks to the `knowledge_chunks` table and their text to the `knowledge_fts` FTS5 table

---

## Step 4 — Verify retrieval is working

Ask your agent something about the indexed content:

> "What does ARCHITECTURE.md say about the session management approach?"

The agent should answer accurately, with its reply drawn from the chunks retrieved by the FTS5 search.

Behind the scenes, the turn pipeline:
1. Extracts keywords from the user's message
2. Runs an FTS5 BM25 query: `keyword1 OR keyword2 OR ...`
3. Returns the top `top_k` chunks ranked by relevance
4. Injects them as a `## Relevant Knowledge` block in the system prompt

---

## Step 5 — Auto-reindex on file changes

If `watchfiles` is installed (it is included in the default Claw install), the `KnowledgeWatcher` automatically re-indexes when workspace files are created, modified, or deleted — no manual `workspace index` needed.

```
[file created/modified] -> clear_source() -> ingest_file() -> upsert to FTS5
[file deleted]          -> clear_source() only
```

The watcher runs as a background asyncio task and is cancelled gracefully when Claw shuts down.

---

## Adjusting chunk parameters

For longer, more narrative documents, increase chunk size and overlap to keep context together:

```toml
[knowledge]
enabled    = true
top_k      = 3
chunk_size = 1000
overlap    = 100
```

For dense reference material (API docs, CSV data), smaller chunks give more precise retrieval:

```toml
[knowledge]
enabled    = true
top_k      = 8
chunk_size = 250
overlap    = 25
```

After changing chunk parameters, reindex to apply:

```powershell
venv\Scripts\python.exe -m claw workspace index
```

---

## Per-agent knowledge

Each agent indexes only its own workspace directory. To give different agents different knowledge bases, put different files in each agent's workspace:

```
~/.claw/agents/main/workspace/       <- main agent's documents
~/.claw/agents/researcher/workspace/ <- researcher's documents
```

Agents do not share knowledge indexes. If you want an agent to draw on another's knowledge, copy the relevant files into its workspace.

---

## Checking what's indexed

The knowledge DB is a plain SQLite file. Query it directly:

```powershell
sqlite3 "$env:USERPROFILE\.claw\knowledge.db" "SELECT source, COUNT(*) FROM knowledge_chunks GROUP BY source;"
```

This shows each indexed file and how many chunks it produced. To clear a specific file and force a fresh reindex:

```powershell
# Run workspace index -- it always calls clear_source() before reingest
venv\Scripts\python.exe -m claw workspace index
```
