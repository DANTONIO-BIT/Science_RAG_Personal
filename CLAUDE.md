# CLAUDE.md — Scientific Knowledge System

> **Estado:** sistema funcional (no skeleton). Última sincronización doc↔código: 2026-05-29.
> Esta doc es la fuente de verdad arquitectónica. Si el código contradice esto, gana el código — anótalo y avísame.

## What this project is

A local-first scientific intelligence system for molecular biology, microbiology, and biotechnology research. It combines a secure API gateway, a semantic RAG engine, an agentic ReAct harness exposed over MCP, and an evolving LLM-generated wiki. The system is designed for a researcher who processes NGS/bioinformatics data and needs to synthesize knowledge from both public literature and private research notes, with strict data governance between them.

The system is **not** a generic chatbot. It is a structured knowledge architecture that protects private research data absolutely, scales to cloud LLMs only when local capacity is insufficient, and accumulates structured knowledge into a persistent wiki.

**Design principle (data sovereignty):** the *code* is shareable and reproducible; the *data* is custodied by the researcher. On any machine, dropping the source files back into `data/` and re-indexing reconstructs the entire knowledge base. See "Portability & reproducible rebuild".

## Architecture layers

```
Layer 1 — Knowledge (data/)
  data/public/          → papers, references, pipelines (shareable)
  data/private/         → hypotheses, notes, internal synthesis (never leaves local)
  data/ngs/             → processed bioinformatics outputs (VCF, BED, DESeq2 tables, reports)

Layer 2 — RAG (infra/rag/)
  Three ChromaDB collections inside one persist_directory:
    "public"  ← data/public/ + data/ngs/ + projects/   (~3322 chunks)
    "private" ← data/private/ ONLY                       (~177 chunks, lab notes)
    "wiki"    ← wiki/auto_generated/ synthesis nodes     (the feedback loop)
  Embeddings: bge-m3 via Ollama (local, multilingual, handles LaTeX), 1024-dim
  Chunking: 1500 chars, 200 overlap (config.yaml)
  Ingest is idempotent AND portable: chunk id = sha256("{repo-relative-path}::{index}")[:32],
    upsert → re-ingest never duplicates and ids survive cloning/moving the repo.

Layer 3 — LLM routing (infra/rag/src/router.py)
  Single-query mode (python agent/science.py "query"):
    High confidence (>= 0.85) → answer from RAG context directly (no LLM)
    Mid  (0.50–0.85)          → local LLM synthesis (qwen3:8b via Ollama)
    Low  (< 0.50)             → cloud escalation (OpenRouter by default; public context only)

Layer 4 — Agent harness + MCP (agent/)
  ReAct loop (agent/harness.py): native tool-calling via Ollama /api/chat, model decides
    when to call tools (no pre-fetch). qwen3 thinking mode shown as [thinking...].
  3 tools: search_memory · save_insight · call_cloud
  MCP server (agent/mcp_server.py): exposes 5 tools to Claude Code (.mcp.json) and
    OpenCode (opencode.json) — search_memory, save_insight, science_ingest,
    science_status, call_cloud. Launched automatically; no manual Python invocation.
```

## Two entry points (important — they differ)

| Mode | Command | Cloud backend | Gate |
|---|---|---|---|
| Single query | `python agent/science.py "..."` | router.py → **OpenRouter** (default) | confidence-based + `confirmed_cloud` |
| Interactive | `python agent/science.py --interactive` | harness → tools/cloud.py → **OpenRouter** | two-step `confirmed` |
| MCP (recommended) | auto-launched in Claude Code / OpenCode | tools/cloud.py → **OpenRouter** (nemotron free) | two-step `confirmed` |

**Cloud provider (unified):** OpenRouter is the default everywhere — `:free` models incur no per-token API billing. Anthropic is **opt-in** (billed as standard API usage): set `llm.cloud.provider: anthropic` in config.yaml or `LLM_CLOUD_PROVIDER=anthropic` in `.env`. Model overrides: `OPENROUTER_MODEL`, `ANTHROPIC_MODEL`.

## Routing logic (single-query mode)

```
USER QUERY
  ↓
RAG retrieval (public + private queried separately, merged by score) — query_full()
  ↓
CONFIDENCE (rank-weighted avg of top-k similarity) — compute_confidence()
  ├── High (>= 0.85) → format RAG context as answer (rag_only)
  ├── Mid  (0.50–0.85) → local LLM synthesis (qwen3:8b)
  └── Low  (< 0.50)  → cloud LLM; PrivacyError if private hits and not confirmed
               ↓
        If confidence >= 0.80 and LLM used → wiki/auto_generated/ node written
```

## Data governance rules (non-negotiable)

1. `data/private/` content **never** enters the `"public"` ChromaDB collection (path-based routing in `ingest._detect_collection_and_project`)
2. When routing to cloud, **only public context** is sent unless the user explicitly confirms (`PrivacyError` guards this in router.py)
3. Raw NGS files (FASTQ, FASTQ.GZ, BAM, CRAM) are **never** ingested into the RAG
4. The `"private"` ChromaDB collection (and `data/private/`) is excluded from git and any sync
5. Source metadata (`_source: "public"|"private"|"ngs"`) is attached to every chunk at ingest time
6. **Wiki nodes tagged `_source: private+public` are private-derived**: their chunks are embedded with `_source="private"` (cloud gate blocks them) and `wiki/auto_generated/` is gitignored, so they never reach the cloud or a public remote

## What is embeddable from NGS outputs

| Format | Embed? | Notes |
|---|---|---|
| FASTQ / BAM / CRAM | NO | Raw sequencing, binary or oversized |
| FASTA (genes, proteins) | YES | Short sequences with biological context |
| VCF (annotated) | YES | Functional variant annotations |
| BED (annotated) | YES | Structured genomic features |
| FastQC / MultiQC reports | YES | QC metrics as text |
| DESeq2 / edgeR tables | YES | Differential expression results |

## Folder structure (actual)

```
secure-ai-agent-architecture/
│
├── agent/                       ← AGENTIC LAYER (ReAct + MCP)
│   ├── harness.py               ← ReAct loop, native tool-calling via Ollama /api/chat
│   ├── mcp_server.py            ← FastMCP server (5 tools) — launched by Claude Code / OpenCode
│   ├── science.py               ← CLI entry (--interactive → harness; "query" → router)
│   ├── prompts/system.md        ← agent system prompt
│   └── tools/
│       ├── memory.py            ← search_memory: RAG public+private + wiki + Engram
│       ├── insight.py           ← save_insight: persist synthesis to wiki + Engram
│       └── cloud.py             ← call_cloud: OpenRouter, two-step confirm gate
│
├── data/                        ← source documents (custodied by researcher, see portability)
│   ├── public/papers/{inbox,indexed}/   ← drop PDFs in inbox → watcher ingests → indexed
│   ├── public/references/{bacteria,eukaryotes,transposons}/
│   ├── private/                 ← gitignored; never synced; never to "public" collection
│   │   └── {hypotheses,notes,synthesis}/
│   └── ngs/{reports,results,sequences}/
│
├── infra/
│   ├── rag/
│   │   ├── src/
│   │   │   ├── ingest.py        ← parse + chunk + embed → ChromaDB (idempotent upsert)
│   │   │   ├── embed.py         ← bge-m3 via Ollama wrapper
│   │   │   ├── query.py         ← query_public/private/full + confidence + format
│   │   │   ├── router.py        ← confidence scoring + LLM routing + wiki auto-write
│   │   │   ├── watcher.py       ← watchdog: auto-ingest new files in data/
│   │   │   └── reingest_all.py  ← clear collections + re-ingest all of data/ (rebuild)
│   │   ├── config/config.yaml   ← thresholds, model names, paths, chunking
│   │   ├── data/chroma_db/      ← ChromaDB persist_directory (gitignored)
│   │   ├── input/               ← staging copies of source PDFs (NOT gitignored — see below)
│   │   ├── requirements.txt     ← Python deps for the RAG/agent stack
│   │   ├── run_ingest.py        ← one-shot ingest entry
│   │   └── logs/
│   └── bridge/
│       └── bridge_cloud.py      ← legacy gated cloud caller (superseded by tools/cloud.py)
│
├── wiki/auto_generated/         ← LLM-written synthesis nodes (.md). May be private-derived.
│
├── gateway/                     ← Express.js secure API gateway (Node.js)
│   ├── constants.js · index.js · schemas.js · validators.js
├── routes/tools.js              ← tool dispatch
├── server.js                    ← Express entry (loopback-only, port 3001)
├── scripts/                     ← PORTABILITY & MIGRATION
│   ├── bootstrap.sh             ← fresh-machine setup (venv, deps, data skeleton, ollama)
│   ├── backup.py                ← bundle data/ + wiki nodes → backups/*.tar.gz (+ manifest)
│   └── restore.py               ← extract bundle + verify + rebuild index from scratch
├── iniciar-RAG.sh / detener-RAG.sh   ← start/stop the watcher + stack
├── .mcp.json                    ← Claude Code MCP config (science server)
├── opencode.json                ← OpenCode MCP config (qwen3:8b + science + notion)
└── projects/science_projects_IA_ML/   ← original papers corpus
```

## LLM Wiki

When a query + synthesis reaches confidence ≥ 0.80 (single-query mode), router.py writes a `.md` node to `wiki/auto_generated/`. Each node has a topic-slug filename, a `_source` tag (`public` or `private+public`), source citations, timestamp, and confidence.

**Feedback loop (wired & semantic):** every wiki node is embedded into the `"wiki"` ChromaDB collection at write time — `save_insight` (`tools/insight.py`) and the router's `_write_wiki_node` both call `ingest_file` on the new `.md`. `query_full` and `search_memory(scope="wiki")` retrieve nodes **semantically**; keyword match remains only as a fallback when the collection is empty (fresh machine pre-reindex). Synthesized knowledge now genuinely improves future retrieval.

**Wiki privacy:** a node whose body carries `_source: private` / `private+public` is embedded with chunk `_source="private"`, so the existing cloud privacy gate (which keys on `_source == "private"`) blocks it from escalation automatically. Public nodes are tagged `_source="wiki"` (cloud-safe).

## Memory backends

- **ChromaDB** — semantic RAG (public + private + wiki collections)
- **wiki/auto_generated/** — synthesis nodes, embedded into the `"wiki"` collection (semantic; keyword fallback)
- **Engram** v1.15.x (`/usr/local/bin/engram`, project `science-agent`) — session/long-term memory, searched via CLI in `tools/memory.py:_search_engram`

## Portability & reproducible rebuild

Goal: push *code* to GitHub, keep *data* private, and rebuild the full system on any machine from the source files alone.

**Reproducibility works.** `infra/rag/src/reingest_all.py` walks `data/` + `wiki/auto_generated/` + `projects/` and re-ingests every supported file with the correct collection routing. `ingest_file` is idempotent (id = sha256(repo-relative-path::index), upsert) so re-running never duplicates, and ids are **portable across machines** (no absolute paths). Same files + same `bge-m3` + same chunking config → byte-stable index. `scripts/restore.py` always does a **clean** rebuild (deletes `chroma_db/` first), so no stale chunks from deleted files survive. Verified: a full clean reindex reproduced identical counts (public 3322 · private 177 · wiki 2).

**Migration tooling (`scripts/`):**
- `scripts/backup.py` → bundles `data/` + `wiki/auto_generated/` into `backups/knowledge-<date>.tar.gz` with a `manifest.json` (sha256 per file). This is your custodied snapshot — **includes the wiki nodes accumulated over time**. `--no-private` excludes private notes for sharing.
- `scripts/restore.py <bundle>` → extracts (with path-traversal guards + sha256 verification), then **rebuilds the index from scratch** (deletes `chroma_db/`, runs `reingest_all`). `--reindex-only` rebuilds from the current `data/` without a bundle.
- `scripts/bootstrap.sh [bundle]` → fresh-machine setup: venv + `pip install` + `npm install` + recreate `data/` skeleton + `.env` from example + `ollama pull bge-m3 qwen3:8b`, then restores the bundle if given.

**Round trip:** `backup.py` on machine A → copy bundle (your custody, never git) → `bootstrap.sh bundle.tar.gz` on machine B → system fully reconstituted, wiki included.

**`.gitignore` — resolved:** only the architecture is committed. ALL of `data/`, `projects/`, `infra/rag/input/`, `wiki/auto_generated/*` (except `.gitkeep`), `backups/`, the vector store, and heavy/binary types (`*.pdf`, `*.png`, `*.sqlite3`, …) are excluded. The `data/` skeleton is recreated by `bootstrap.sh`, not versioned.

## Current build status

| Component | Status |
|---|---|
| Express gateway (Node.js) | Built, functional (loopback :3001) |
| infra/rag/src/ | **Complete & functional** — ingest, embed, query, router, watcher, reingest |
| ChromaDB "public" | **~3322 chunks** (papers + projects corpus) |
| ChromaDB "private" | **~177 chunks** (lab notes) — governance exercised |
| ChromaDB "wiki" | **Active** — synthesis nodes embedded; semantic feedback loop |
| agent/ harness + tools | **Complete** — ReAct loop, 3 tools |
| agent/mcp_server.py | **Active** in Claude Code & OpenCode (5 tools) |
| wiki feedback loop | **Wired** — nodes embedded on write, retrieved semantically, privacy-tagged |
| Cloud path | **Unified on OpenRouter** (default); Anthropic opt-in & billed |
| Portability tooling | **Built** — scripts/bootstrap.sh + backup.py + restore.py |
| bridge_cloud.py | Legacy skeleton — superseded by tools/cloud.py |
| science/conda-envs/ | Empty |

## Running

```bash
# Gateway
npm install && npm start          # 127.0.0.1:3001 ; curl http://127.0.0.1:3001/health

# RAG stack (watcher)
bash iniciar-RAG.sh               # checks Ollama + models, launches watcher
bash detener-RAG.sh

# Agent
python agent/science.py --interactive       # chat (harness + tools)
python agent/science.py "your question"      # single query (router)

# MCP: auto-starts in Claude Code (.mcp.json) and OpenCode (opencode.json)
```

## Key constraints inherited from gateway design

- No delete operations in the gateway — intentional
- Filesystem ops sandboxed to `SAFE_WORKSPACE_ROOT`
- Server binds to loopback only (`127.0.0.1`)
- Secrets in `.env` only, never passed to model
- Rate limit: 60 req/min

## Environment variables (.env)

- `OPENROUTER_API_KEY` — cloud escalation via harness/MCP (default model `nvidia/nemotron-3-super-120b-a12b:free`, override with `OPENROUTER_MODEL`)
- `ANTHROPIC_API_KEY` — required only for single-query cloud path in router.py

## Scientific domain

Molecular biology, microbiology, and biotechnology:
- Bacterial stress response (Hfq, RNase H, R-loops, (p)ppGpp/stringent response)
- Pathogenesis (Salmonella, antimicrobial resistance)
- NGS/genomics data integration
- AI-assisted research workflows
