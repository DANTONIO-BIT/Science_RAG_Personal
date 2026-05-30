"""
LLM routing layer.

Confidence thresholds (from config.yaml) determine where a query goes:
  High  (>= confidence_high) → local RAG answer, no LLM needed
  Mid   (between thresholds) → local LLM + RAG context
  Low   (<  confidence_low)  → cloud LLM (OpenRouter by default; public context only)

Private context NEVER travels to cloud without explicit user confirmation.
"""
from __future__ import annotations

import json
import logging
import os
import re
import yaml
from datetime import datetime
from pathlib import Path

import httpx

from .query import query_full, compute_confidence, format_context

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
REPO_ROOT = Path(__file__).parent.parent.parent.parent

_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


class PrivacyError(Exception):
    """Raised when private data would be sent to an external service without confirmation."""


def route(query: str, confirmed_cloud: bool = False, silent: bool = False) -> dict:
    """
    Full pipeline: retrieve → score → route → respond.

    Args:
        query: The user's scientific question.
        confirmed_cloud: Set True if the user has already confirmed sending private context
                         to the cloud. Only relevant when private hits exist.

    Returns:
        {
          "response": str,
          "confidence": float,
          "llm_used": "rag_only" | "local" | "cloud",
          "context_sources": list[str],   # "public" | "private"
          "wiki_written": str | None      # path if a wiki node was created
        }
    """
    cfg = _load_config()
    thresholds = cfg["routing"]
    wiki_cfg = cfg["wiki"]

    # 1. Retrieve
    results = query_full(query, n_results=5)
    confidence = compute_confidence(results)
    context_sources = list({r["_source"] for r in results})
    has_private = "private" in context_sources

    logger.info(
        "Query confidence=%.3f | sources=%s | hits=%d",
        confidence, context_sources, len(results),
    )

    wiki_written: str | None = None

    # 2. Route by confidence
    if confidence >= thresholds["confidence_high"]:
        # High confidence — answer directly from RAG context, no LLM needed
        response = format_context(results)
        llm_used = "rag_only"

    elif confidence >= thresholds["confidence_low"]:
        # Mid confidence — local LLM synthesis
        response = _call_local_llm(query, results, silent=silent)
        llm_used = "local"

    else:
        # Low confidence — escalate to Claude API (public context only unless confirmed)
        public_results = [r for r in results if r["_source"] == "public"]

        if has_private and not confirmed_cloud:
            raise PrivacyError(
                "Private context found. Call route(query, confirmed_cloud=True) "
                "after obtaining explicit user confirmation to include private chunks, "
                "or use query_public() to restrict to public knowledge only."
            )

        context_for_cloud = public_results if (has_private and not confirmed_cloud) else results
        response = _call_cloud_llm(query, context_for_cloud)
        llm_used = "cloud"

    # 3. Auto-write wiki node if quality threshold met
    if confidence >= wiki_cfg["quality_threshold"] and llm_used in ("local", "cloud"):
        wiki_written = _write_wiki_node(query, response, results, confidence)

    return {
        "response": response,
        "confidence": confidence,
        "llm_used": llm_used,
        "context_sources": context_sources,
        "wiki_written": wiki_written,
    }


def _build_prompt(query: str, context: list[dict]) -> str:
    """Assemble a system + user prompt for scientific synthesis."""
    context_block = format_context(context)
    return (
        "You are a scientific research assistant specializing in molecular biology, "
        "microbiology, and biotechnology. Answer questions precisely, cite sources "
        "when available, and flag uncertainty clearly.\n\n"
        f"Context from knowledge base:\n{context_block}\n\n"
        f"Question: {query}\n\n"
        "Provide a concise, accurate scientific answer based on the context above. "
        "If the context is insufficient, say so explicitly."
    )


def _call_local_llm(prompt: str, context: list[dict], silent: bool = False) -> str:
    """
    Call local LLM via Ollama using streaming.
    Streaming avoids ReadTimeout on large models (qwen3:8b, etc.) — tokens arrive
    incrementally so the connection never idles long enough to time out.

    silent=False (default): prints tokens to stdout in real-time (CLI mode).
    silent=True: suppresses stdout output — required for MCP server mode where
                 stdout is reserved for the JSON-RPC protocol and printing would
                 corrupt the communication channel.
    """
    cfg = _load_config()
    local_cfg = cfg["llm"]["local"]
    url = f"{local_cfg['base_url']}/api/generate"

    full_prompt = _build_prompt(prompt, context)
    payload = {
        "model": local_cfg["model"],
        "prompt": full_prompt,
        "stream": True,
        "options": {
            "temperature": local_cfg.get("temperature", 0.2),
            # 4096 covers qwen3 thinking phase (300-800 tokens) + full scientific response
            "num_predict": 4096,
        },
    }

    tokens: list[str] = []
    thinking_shown = False
    try:
        with httpx.stream("POST", url, json=payload,
                          timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)) as resp:
            # connect=30s; read=None so thinking phase doesn't trigger timeout
            resp.raise_for_status()
            if not silent:
                print()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    import json as _json
                    chunk = _json.loads(line)
                except ValueError:
                    continue
                # Show thinking indicator once when model enters reasoning phase
                if not silent and not thinking_shown and chunk.get("thinking"):
                    print("[thinking...]", flush=True)
                    thinking_shown = True
                token = chunk.get("response", "")
                if token:
                    if not silent:
                        print(token, end="", flush=True)
                    tokens.append(token)
                if chunk.get("done", False):
                    break
            if not silent:
                print()
    except httpx.ConnectError:
        logger.error("Ollama not running at %s", local_cfg["base_url"])
        raise RuntimeError(
            f"Local LLM unavailable. Start Ollama: `ollama serve` then ensure model is ready: "
            f"`ollama run {local_cfg['model']}`"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama connect timeout. Is `ollama serve` running at {local_cfg['base_url']}?"
        )

    return "".join(tokens).strip()


def _call_cloud_llm(prompt: str, context: list[dict]) -> str:
    """
    Escalate to a cloud LLM. Provider is OpenRouter by default (free tier, no
    per-token API billing on :free models); Anthropic is opt-in via
    config llm.cloud.provider=anthropic or env LLM_CLOUD_PROVIDER=anthropic.

    Raises PrivacyError if private chunks sneak in without confirmation.
    """
    if any(r.get("_source") == "private" for r in context):
        raise PrivacyError("Private context must not reach the cloud without explicit confirmation.")

    cfg = _load_config()
    cloud_cfg = cfg["llm"]["cloud"]
    provider = os.getenv("LLM_CLOUD_PROVIDER", cloud_cfg.get("provider", "openrouter")).lower()
    full_prompt = _build_prompt(prompt, context)

    if provider == "anthropic":
        return _call_anthropic(full_prompt, cloud_cfg)
    return _call_openrouter(full_prompt, cloud_cfg)


def _call_openrouter(full_prompt: str, cloud_cfg: dict) -> str:
    """Primary cloud path — OpenRouter chat completions."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set in environment / .env")

    model = os.getenv("OPENROUTER_MODEL", cloud_cfg["model"])
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3001",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": full_prompt}],
            "max_tokens": cloud_cfg.get("max_tokens", 4096),
            "temperature": cloud_cfg.get("temperature", 0.3),
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_anthropic(full_prompt: str, cloud_cfg: dict) -> str:
    """Opt-in cloud path — Anthropic API (billed as standard API usage)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in environment / .env")

    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic SDK required. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("ANTHROPIC_MODEL", cloud_cfg.get("anthropic_model", "claude-opus-4-8"))
    message = client.messages.create(
        model=model,
        max_tokens=cloud_cfg.get("max_tokens", 4096),
        messages=[{"role": "user", "content": full_prompt}],
    )
    return message.content[0].text.strip()


def _request_cloud_confirmation(query: str, context: list[dict]) -> bool:
    """
    Interactive stdin prompt: ask user to confirm before sending context to cloud.
    Returns True if confirmed, False if denied.
    Only relevant in CLI/interactive usage — headless callers should pass confirmed_cloud=True.
    """
    private_files = [
        r["metadata"].get("filename", "?")
        for r in context
        if r.get("_source") == "private"
    ]
    print("\n⚠️  PRIVACY GATE ⚠️")
    print(f"Query: {query}")
    print(f"Private files that would be sent to cloud: {private_files}")
    answer = input("Send to Claude API? [y/N]: ").strip().lower()
    return answer == "y"


def _write_wiki_node(
    query: str,
    response: str,
    context: list[dict],
    confidence: float,
) -> str | None:
    """Write a structured wiki node to wiki/auto_generated/. Returns path or None."""
    cfg = _load_config()
    wiki_dir = REPO_ROOT / cfg["wiki"]["output_dir"]
    wiki_dir.mkdir(parents=True, exist_ok=True)

    max_len = cfg["wiki"].get("max_node_length", 2000)
    truncated = response[:max_len] + ("…" if len(response) > max_len else "")

    # Build slug from first 6 words of query
    slug_words = re.sub(r"[^\w\s]", "", query.lower()).split()[:6]
    slug = "_".join(slug_words) or "untitled"
    filename = f"{slug}.md"
    dest = wiki_dir / filename

    sources = list({r["metadata"].get("filename", "?") for r in context})
    has_private = any(r.get("_source") == "private" for r in context)
    source_tag = "private+public" if has_private else "public"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    content = (
        f"# {query}\n\n"
        f"_Auto-generated · {timestamp} · confidence: {confidence:.3f} · _source: {source_tag}_\n\n"
        f"## Summary\n\n{truncated}\n\n"
        f"## Sources\n\n"
        + "\n".join(f"- {s}" for s in sorted(sources))
        + "\n"
    )

    dest.write_text(content, encoding="utf-8")
    logger.info("Wiki node written: %s", dest)

    # Close the feedback loop: embed the node so it improves future retrieval.
    # The node body carries "_source: <tag>", so ingest tags private-derived
    # nodes as _source="private" (cloud gate blocks them). Best-effort.
    try:
        from .ingest import ingest_file
        ingest_file(dest)
    except Exception as e:
        logger.warning("Wiki node embed failed (file kept): %s", e)

    return str(dest)
