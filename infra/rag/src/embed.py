"""
Embedding wrapper — bge-m3 via Ollama.
Swap model in config.yaml; this module never references model names directly.
"""
from __future__ import annotations

import logging
import yaml
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

# Module-level config cache
_config: dict | None = None


def _load_config() -> dict:
    global _config
    if _config is None:
        with open(CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config


def _cfg() -> dict:
    return _load_config()["embedding"]


def get_embedding(text: str) -> list[float]:
    """Return embedding vector for a single text string via Ollama."""
    cfg = _cfg()
    url = f"{cfg['base_url']}/api/embeddings"
    payload = {"model": cfg["model"], "prompt": text}

    resp = httpx.post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    embedding = resp.json()["embedding"]

    if len(embedding) != cfg["dimensions"]:
        logger.warning(
            "Embedding dimension mismatch: expected %d, got %d",
            cfg["dimensions"],
            len(embedding),
        )
    return embedding


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Return embeddings for a list of texts, respecting batch_size from config."""
    cfg = _cfg()
    batch_size: int = cfg.get("batch_size", 32)
    results: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.debug("Embedding batch %d–%d of %d", i, i + len(batch), len(texts))
        for text in batch:
            results.append(get_embedding(text))

    return results
