# AGENTS.md — Science Agent Architecture

This file is read automatically by **OpenCode**, **Claude Code CLI**, and **Claude Cowork**.  
It describes what the science agent is, how to use it, and how every tool/skill is wired up.

---

## What this project is

A **local-first scientific intelligence system** for molecular biology, microbiology, and
biotechnology research. It:

- Indexes research papers and private notes into a local vector database (ChromaDB)
- Answers scientific questions using semantic RAG + local LLM (qwen3:8b via Ollama)
- Escalates to Claude API only when confidence is low, and only with public context
- Auto-generates structured wiki nodes from high-quality answers
- Exposes everything as MCP tools (OpenCode / Claude Code) and a CLI (terminal / Cowork)

**Private data never leaves the machine.** The privacy gate is enforced in code, not policy.

---

## Science agent — three ways to use it

### 1. Terminal / Cowork (CLI)

```bash
# Ask a single question
python agent/science.py "What is the role of Hfq in Salmonella stress response?"

# Interactive session (REPL)
python agent/science.py --interactive

# Ingest a new paper or folder
python agent/science.py --ingest data/public/papers/inbox/new_paper.pdf
python agent/science.py --ingest projects/Hfq-project/inbox/

# Check knowledge base status
python agent/science.py --status

# Force query against a specific collection
python agent/science.py --collection public "What do the public papers say about R-loops?"
python agent/science.py --collection private "My hypotheses on RNase H"

# Skip LLM synthesis — return raw RAG chunks only
python agent/science.py --context-only "Hfq binding affinity"

# Force cloud escalation (Claude API, public context only)
python agent/science.py --cloud "Compare AMR mechanisms in Gram-negative bacteria"

# Verbose output (shows routing decision + confidence)
python agent/science.py -v "R-loop resolution pathways"
```

### 2. OpenCode (MCP server — auto-discovered via opencode.json)

OpenCode reads `opencode.json` at project root and auto-starts the science MCP server.
No manual setup required — just open the project in OpenCode.

The model is `ollama/qwen3:8b`. Available MCP tools in OpenCode:

| Tool | Description |
|---|---|
| `science_query` | Ask the knowledge base a scientific question (RAG + LLM routing) |
| `science_ingest` | Add a file or folder to the knowledge base |
| `science_status` | Check ChromaDB chunk counts and Ollama reachability |

**Example prompts in OpenCode:**
- *"Use science_query to explain Hfq's role in post-transcriptional regulation"*
- *"Ingest the papers in projects/Hfq-project/inbox/ using science_ingest"*
- *"Run science_status to check if the knowledge base is ready"*

### 3. Claude Code CLI (MCP server — auto-discovered via .mcp.json)

`.mcp.json` at project root registers the science server with Claude Code CLI.
Run `claude` from this directory — the science tools are available automatically.

Same three tools as OpenCode: `science_query`, `science_ingest`, `science_status`.

---

## Setup — first time

### Prerequisites

```bash
# 1. Ollama (local LLM + embeddings)
brew install ollama          # macOS
ollama serve                 # start the daemon (keep running)
ollama pull qwen3:8b         # local LLM (~5 GB)
ollama pull bge-m3           # embedding model (~550 MB)

# 2. Python dependencies
pip install -r infra/rag/requirements.txt --break-system-packages

# 3. Anthropic API key (only needed for cloud fallback)
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
```

### First ingest (index all existing papers)

```bash
# Batch-ingest the full existing corpus (~56 PDFs)
python infra/rag/run_ingest.py

# Or ingest a specific project
python infra/rag/run_ingest.py --path projects/Hfq-project/inbox/

# Check results
python agent/science.py --status
```

### Auto-watcher (optional — drops files, they get indexed automatically)

```bash
python -m infra.rag.src.watcher    # run from repo root; Ctrl+C to stop
```

Drop any PDF/MD/TXT into `projects/{name}/inbox/` or `data/public/` and it is
ingested within seconds.

---

## Architecture at a glance

```
USER QUERY  (CLI / OpenCode MCP / Claude Code MCP)
     │
     ▼
agent/science.py  or  agent/mcp_server.py
     │
     ▼
infra/rag/src/router.py  ← confidence scoring + routing decision
     │
     ├─ High confidence (≥ 0.85)  →  RAG context returned directly  (no LLM)
     ├─ Mid confidence  (≥ 0.50)  →  qwen3:8b via Ollama  (local synthesis)
     └─ Low confidence  (< 0.50)  →  Claude API  (public context only)
                                       └─ PrivacyError if private chunks present
                                            without confirmed_cloud=True
     │
     ▼
wiki/auto_generated/{slug}.md   ← written if confidence ≥ 0.80

ChromaDB collections (infra/rag/data/chroma_db/)
  "public"   ← data/public/, data/ngs/, projects/{name}/inbox/
  "private"  ← data/private/, projects/{name}/private/
```

---

## Project folder structure for new research projects

```
projects/
  {project-name}/
    inbox/      ← drop PDFs/notes here → indexed to "public" collection
                   (project_id = {project-name} for per-project filtering)
    private/    ← hypotheses, notes → indexed to "private" collection
                   gitignored, never synced
```

**Existing projects:**
- `projects/Hfq-project/` — Hfq RNA chaperone research
- `projects/science_projects_IA_ML/` — existing corpus of ~56 papers
- `projects/_template/` — copy this to start a new project

---

## Data governance rules

1. `data/private/` and `projects/{name}/private/` content goes **only** into the
   `"private"` ChromaDB collection — never the `"public"` one
2. When routing to Claude API, **only public context** is sent unless the user explicitly
   confirms (`confirmed_cloud=True`)
3. Raw NGS files (`.fastq`, `.fastq.gz`, `.bam`, `.cram`) are **never** ingested
4. The `"private"` ChromaDB collection is **gitignored** and never synced
5. Every chunk carries `_source: "public" | "private"` metadata — the privacy gate
   checks this at call time in `router.py`

---

## Key files

| File | Purpose |
|---|---|
| `agent/science.py` | CLI entry point — terminal / Cowork |
| `agent/mcp_server.py` | MCP server — OpenCode + Claude Code |
| `agent/SKILL.md` | Cowork skill definition (auto-loaded) |
| `agent/prompts/system.md` | Scientific system prompt |
| `infra/rag/src/ingest.py` | Parse → chunk → embed → ChromaDB |
| `infra/rag/src/query.py` | Retrieval + confidence scoring |
| `infra/rag/src/router.py` | LLM routing (local / cloud / RAG-only) |
| `infra/rag/src/embed.py` | bge-m3 embedding wrapper (Ollama) |
| `infra/rag/src/watcher.py` | File watcher for auto-ingest |
| `infra/rag/config/config.yaml` | All thresholds, model names, paths |
| `infra/rag/run_ingest.py` | Batch ingest script |
| `opencode.json` | OpenCode config (model + MCP servers) |
| `.mcp.json` | Claude Code CLI MCP config |
| `wiki/auto_generated/` | LLM-generated knowledge nodes |

---

## Config reference (infra/rag/config/config.yaml)

```yaml
embedding:
  model: bge-m3          # Ollama embedding model
  base_url: http://localhost:11434

llm:
  local:
    model: qwen3:8b      # Ollama LLM
    base_url: http://localhost:11434
  cloud:
    model: claude-opus-4-6  # Anthropic cloud fallback

routing:
  confidence_high: 0.85  # above this → RAG only, no LLM call
  confidence_low:  0.50  # below this → escalate to Claude API

wiki:
  quality_threshold: 0.80   # above this → auto-write wiki node
  output_dir: wiki/auto_generated/
```

---

## Running the Express gateway (Node.js layer)

The existing Express gateway (port 3001) is a separate layer for API security.
It is **not required** for the science agent to function.

```bash
npm install
npm start           # binds to 127.0.0.1:3001
curl http://127.0.0.1:3001/health
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Ollama not running` | Run `ollama serve` in a terminal |
| `model not found` | Run `ollama pull qwen3:8b` and `ollama pull bge-m3` |
| `ChromaDB: not initialized` | Run `python infra/rag/run_ingest.py` |
| `ANTHROPIC_API_KEY not set` | Add it to `.env` — only needed for cloud fallback |
| `ModuleNotFoundError: mcp` | Run `pip install mcp --break-system-packages` |
| `PrivacyError` in cloud mode | Use `--collection public` flag or confirm cloud in code |
