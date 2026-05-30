#!/usr/bin/env python3
"""
Science Agent — MCP Server

Exposes the RAG knowledge base and memory tools as native MCP tools.
Both Claude Code (.mcp.json) and OpenCode (opencode.json) launch this
automatically — no manual Python invocation needed.

Tools:
  search_memory   — query all memory sources (RAG + wiki + Engram)
  save_insight    — persist a synthesis to wiki + Engram
  science_ingest  — add a file or folder to the knowledge base
  science_status  — check collection stats and readiness

Do NOT run interactively — stdout is reserved for JSON-RPC protocol.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AGENT_DIR = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENT_DIR))

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "Science Agent",
    instructions=(
        "You have access to a local scientific knowledge base built from research papers "
        "on molecular biology, microbiology, and biotechnology (Hfq, Salmonella, R-loops, "
        "AMR, NGS). "
        "\n\nWORKFLOW:\n"
        "1. Always call search_memory FIRST before answering any scientific question.\n"
        "2. If local knowledge is sufficient, answer directly and call save_insight if the "
        "synthesis is notable.\n"
        "3. If local knowledge is clearly insufficient, call call_cloud with confirmed=False "
        "to show the user a preview of what would be sent to the cloud. WAIT for the user "
        "to reply with explicit confirmation ('yes', 'proceed', etc.) before calling "
        "call_cloud again with confirmed=True.\n"
        "4. NEVER include private research notes in the cloud prompt — public context only.\n"
        "\nAlways cite the source files returned in search results."
    ),
)


# ── Tool: search_memory ───────────────────────────────────────────────────────

@mcp.tool()
def search_memory(query: str, scope: str = "all") -> str:
    """
    Search the scientific knowledge base and return relevant context.

    Searches ChromaDB (public papers + private notes), auto-generated wiki nodes,
    and Engram session memory. Returns ranked chunks with confidence score.

    Args:
        query: Natural-language search query.
        scope: "all" (default), "public", "private", "wiki", or "engram".

    Returns:
        Formatted context with confidence score and source citations.
    """
    try:
        from tools.memory import search_memory as _search
        return _search(query=query, scope=scope)
    except Exception as e:
        return f"search_memory error: {e}"


# ── Tool: save_insight ────────────────────────────────────────────────────────

@mcp.tool()
def save_insight(title: str, content: str) -> str:
    """
    Persist a synthesis or finding to long-term memory (wiki + Engram).

    Call this after generating a high-quality answer worth retaining across sessions.
    The insight becomes searchable via search_memory in future sessions.

    Args:
        title:   Short descriptive title (5–10 words).
        content: Insight content to save (plain text or markdown).

    Returns:
        Confirmation of where the insight was saved.
    """
    try:
        from tools.insight import save_insight as _save
        return _save(title=title, content=content)
    except Exception as e:
        return f"save_insight error: {e}"


# ── Tool: science_ingest ──────────────────────────────────────────────────────

@mcp.tool()
def science_ingest(path: str) -> str:
    """
    Ingest a file or directory into the scientific knowledge base.

    Supported: PDF, Markdown, TXT, FASTA, VCF, BED, TSV, CSV, HTML.
    Raw NGS files (FASTQ, BAM, CRAM) are rejected automatically.

    Path routing rules (collection and project_id derived from path):
      data/public/**           → public collection
      data/private/**          → private collection
      data/ngs/**              → public collection (processed outputs)
      projects/{name}/inbox/   → public, project_id={name}
      projects/{name}/private/ → private, project_id={name}

    Args:
        path: Absolute or repo-relative path to a file or directory.

    Returns:
        Chunk counts per file, or error message.
    """
    try:
        from infra.rag.src.ingest import ingest_file
    except ImportError as e:
        return f"ERROR: {e}\nRun: pip install -r infra/rag/requirements.txt"

    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / path

    if not target.exists():
        return f"ERROR: path not found: {target}"

    supported = {".pdf", ".md", ".txt", ".fasta", ".vcf", ".bed", ".tsv", ".csv", ".html"}

    if target.is_file():
        try:
            chunks = ingest_file(target)
            return f"Ingested: {target.name} → {chunks} chunks"
        except Exception as e:
            return f"ERROR ingesting {target.name}: {e}"

    files = [f for f in target.rglob("*") if f.is_file() and f.suffix.lower() in supported]
    if not files:
        return f"No supported files in {target}"

    lines = [f"Ingesting {len(files)} files from {target.name}/\n"]
    ok = err = 0
    for f in files:
        try:
            chunks = ingest_file(f)
            lines.append(f"  OK  {f.name} → {chunks} chunks")
            ok += 1
        except Exception as e:
            lines.append(f"  ERR {f.name}: {e}")
            err += 1

    lines.append(f"\nDone: {ok} ingested, {err} failed.")
    return "\n".join(lines)


# ── Tool: science_status ──────────────────────────────────────────────────────

@mcp.tool()
def science_status() -> str:
    """
    Check the state of the scientific knowledge base.

    Returns chunk counts per ChromaDB collection, wiki node count,
    and whether Ollama is reachable with the required models.
    """
    import httpx
    import yaml

    cfg_path = REPO_ROOT / "infra/rag/config/config.yaml"
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        return f"ERROR reading config: {e}"

    lines = ["Science Knowledge Base Status\n"]

    try:
        import chromadb
        persist_path = REPO_ROOT / cfg["chroma"]["persist_directory"]
        if not persist_path.exists():
            lines.append("ChromaDB: not initialized — run: python infra/rag/run_ingest.py")
        else:
            client = chromadb.PersistentClient(path=str(persist_path))
            for name in ("public", "private", "wiki"):
                try:
                    count = client.get_collection(name).count()
                    lines.append(f"  {name:<10} {count:>6} chunks")
                except Exception:
                    lines.append(f"  {name:<10}       0 chunks")
    except ImportError:
        lines.append("ChromaDB: not installed")

    wiki_dir = REPO_ROOT / cfg["wiki"]["output_dir"]
    wiki_count = len(list(wiki_dir.glob("*.md"))) if wiki_dir.exists() else 0
    lines.append(f"  {'wiki':<10} {wiki_count:>6} nodes")

    ollama_url = cfg["embedding"]["base_url"]
    try:
        r = httpx.get(f"{ollama_url}/api/tags", timeout=3.0)
        models = [m["name"] for m in r.json().get("models", [])]
        for model_key in ("embedding.model", "llm.local.model"):
            parts = model_key.split(".")
            m = cfg
            for p in parts:
                m = m[p]
            ok = any(m in name for name in models)
            lines.append(f"  {m:<28} {'OK' if ok else 'MISSING — ollama pull ' + m}")
        lines.append(f"\nOllama: {ollama_url}")
    except Exception:
        lines.append(f"\nOllama: UNREACHABLE at {ollama_url} — run: ollama serve")

    return "\n".join(lines)


# ── Tool: call_cloud ──────────────────────────────────────────────────────────

@mcp.tool()
def call_cloud(prompt: str, confirmed: bool = False) -> str:
    """
    Escalate to a cloud LLM (OpenRouter) when local knowledge is insufficient.

    TWO-STEP GATE — you MUST follow this protocol:
      Step 1: call with confirmed=False → shows the user a preview + asks confirmation.
      Step 2: after the user explicitly says yes, call again with confirmed=True to execute.

    PRIVACY RULE: NEVER include private research notes in the prompt.
    Only public corpus context may be sent to the cloud.

    Args:
        prompt:    Complete prompt for the cloud model (public context only).
        confirmed: False (default) = show preview and ask. True = execute after user confirmed.

    Returns:
        Preview string (if confirmed=False) or cloud model response (if confirmed=True).
    """
    try:
        from tools.cloud import call_cloud as _call
        return _call(prompt=prompt, confirmed=confirmed)
    except Exception as e:
        return f"call_cloud error: {e}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
