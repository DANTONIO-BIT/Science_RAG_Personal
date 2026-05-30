"""
Unified memory retrieval: ChromaDB (public + private), wiki nodes, Engram.
Single tool surface — the model picks scope, this module does the routing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from infra.rag.src.query import (  # noqa: E402
    query_public,
    query_private,
    query_wiki,
    compute_confidence,
    format_context,
)

ENGRAM_BIN = "/usr/local/bin/engram"
ENGRAM_PROJECT = "science-agent"
WIKI_DIR = REPO_ROOT / "wiki" / "auto_generated"


def search_memory(query: str, scope: str = "all") -> str:
    """
    Search all memory sources and return ranked, formatted context.

    scope options:
      all     — RAG public + private + wiki + Engram (default)
      public  — ChromaDB public collection only (papers, NGS)
      private — ChromaDB private collection only (notes, hypotheses)
      wiki    — auto-generated wiki nodes only
      engram  — Engram session memory only
    """
    results: list[dict] = []

    if scope in ("all", "public"):
        results.extend(query_public(query, n_results=4))
    if scope in ("all", "private"):
        results.extend(query_private(query, n_results=3))
    if scope in ("all", "wiki"):
        results.extend(_search_wiki(query))
    if scope in ("all", "engram"):
        results.extend(_search_engram(query))

    if not results:
        return "No relevant information found in knowledge base."

    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    top = results[:6]

    rag_hits = [r for r in top if r["_source"] in ("public", "private")]
    confidence = compute_confidence(rag_hits) if rag_hits else 0.0
    sources = sorted({r["_source"] for r in top})

    header = f"confidence: {confidence:.3f} | sources: {', '.join(sources)}\n\n"
    return header + format_context(top)


def _search_wiki(query: str, n: int = 3) -> list[dict]:
    """
    Semantic search over the embedded wiki collection (the feedback loop).
    Falls back to keyword search over the raw .md files when the collection is
    empty (e.g. before the first reindex on a fresh machine).
    """
    semantic = query_wiki(query, n_results=n)
    if semantic:
        return semantic
    return _search_wiki_keyword(query, n)


def _search_wiki_keyword(query: str, n: int = 3) -> list[dict]:
    """Keyword fallback over wiki/auto_generated/*.md."""
    if not WIKI_DIR.exists():
        return []

    terms = set(query.lower().split())
    hits: list[dict] = []

    for md in WIKI_DIR.glob("*.md"):
        text = md.read_text(encoding="utf-8", errors="replace")
        matched = sum(1 for t in terms if t in text.lower())
        if matched == 0:
            continue
        score = round((matched / max(len(terms), 1)) * 0.75, 4)  # cap at 0.75 (keyword-only)
        hits.append({
            "text": text[:1200],
            "metadata": {"filename": md.name, "_source": "wiki", "chunk_index": 0},
            "score": score,
            "_source": "wiki",
        })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:n]


def _search_engram(query: str, n: int = 3) -> list[dict]:
    """Search Engram persistent memory via CLI."""
    try:
        proc = subprocess.run(
            [ENGRAM_BIN, "search", query,
             "--project", ENGRAM_PROJECT,
             "--limit", str(n)],
            capture_output=True, text=True, timeout=8,
        )
        text = proc.stdout.strip()
        if proc.returncode == 0 and text:
            return [{
                "text": text,
                "metadata": {"filename": "engram_memory", "_source": "engram", "chunk_index": 0},
                "score": 0.6,
                "_source": "engram",
            }]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []
