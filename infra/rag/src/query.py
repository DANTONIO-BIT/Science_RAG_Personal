"""
RAG retrieval layer.

Three query modes:
  query_public   → searches "public" collection only (safe to forward to cloud)
  query_private  → searches "private" collection only (never leaves local)
  query_full     → searches both, merges results by relevance score

Every result carries _source metadata so the caller knows its provenance.
"""
from __future__ import annotations

import logging
import yaml
from pathlib import Path

import chromadb

from .embed import get_embedding

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _get_client() -> chromadb.PersistentClient:
    cfg = _load_config()
    repo_root = Path(__file__).parent.parent.parent.parent
    persist_path = repo_root / cfg["chroma"]["persist_directory"]
    persist_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_path))


def _query_collection(collection_name: str, text: str, n_results: int) -> list[dict]:
    """Query a single ChromaDB collection. Returns [] if collection is empty."""
    client = _get_client()
    try:
        col = client.get_collection(collection_name)
    except Exception:
        logger.debug("Collection '%s' does not exist yet — skipping.", collection_name)
        return []

    count = col.count()
    if count == 0:
        return []

    n_results = min(n_results, count)
    embedding = get_embedding(text)

    results = col.query(
        query_embeddings=[embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict] = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
                "text": doc,
                "metadata": meta,
                "distance": dist,
                # Cosine distance in ChromaDB: 0=identical, 2=opposite → map to 0–1 similarity
                "score": max(0.0, 1.0 - dist),
                "_source": meta.get("_source", collection_name),
            }
        )
    return hits


def query_public(text: str, n_results: int = 5) -> list[dict]:
    """
    Query the public collection.
    Results are safe to include as context in cloud LLM calls.
    """
    return _query_collection("public", text, n_results)


def query_private(text: str, n_results: int = 5) -> list[dict]:
    """
    Query the private collection.
    Results must never be forwarded to external services without explicit user confirmation.
    """
    return _query_collection("private", text, n_results)


def query_wiki(text: str, n_results: int = 3) -> list[dict]:
    """
    Query the wiki collection — auto-generated synthesis nodes (the RAG feedback
    loop). Each result's _source is "wiki" (cloud-safe) or "private" (private-derived
    node: the privacy gate must block it from the cloud).
    """
    return _query_collection("wiki", text, n_results)


def query_full(text: str, n_results: int = 5) -> list[dict]:
    """
    Query public + private + wiki collections and merge by score (best first).
    Each result includes _source: "public" | "private" | "wiki".
    Wiki hits close the feedback loop: past synthesis improves future retrieval.
    """
    pub = query_public(text, n_results)
    priv = query_private(text, n_results)
    wik = query_wiki(text, n_results)
    merged = sorted(pub + priv + wik, key=lambda r: r["score"], reverse=True)
    return merged[:n_results]


def compute_confidence(results: list[dict]) -> float:
    """
    Derive a 0–1 confidence score from the top-k retrieval scores.
    Uses rank-weighted average (top result counts most).
    Returns 0.0 if no results.
    """
    if not results:
        return 0.0
    weights = [1 / (i + 1) for i in range(len(results))]
    scores = [r["score"] for r in results]
    weighted_sum = sum(w * s for w, s in zip(weights, scores))
    weight_total = sum(weights)
    return round(weighted_sum / weight_total, 4)


def format_context(results: list[dict]) -> str:
    """
    Format retrieved chunks as a prompt-ready context block.
    Annotates each chunk with its source file and collection.
    """
    if not results:
        return "[No relevant context found in knowledge base.]"

    lines: list[str] = ["=== Retrieved Context ===\n"]
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        filename = meta.get("filename", "unknown")
        source = r.get("_source", "unknown")
        score = r.get("score", 0.0)
        chunk_idx = meta.get("chunk_index", "?")
        lines.append(
            f"[{i}] {filename}  (source: {source}, chunk #{chunk_idx}, score: {score:.3f})"
        )
        lines.append(r["text"])
        lines.append("")

    return "\n".join(lines)
