"""
Persist synthesized insights to long-term memory: wiki node + Engram.
Called by the model after generating an answer worth remembering.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
WIKI_DIR = REPO_ROOT / "wiki" / "auto_generated"
ENGRAM_BIN = "/usr/local/bin/engram"
ENGRAM_PROJECT = "science-agent"


def save_insight(title: str, content: str) -> str:
    """
    Write a wiki node and save to Engram.
    Returns a confirmation string for the model to include in its response.
    """
    saved: list[str] = []

    wiki_path = _write_wiki(title, content)
    if wiki_path:
        saved.append(f"wiki/{Path(wiki_path).name}")

    if _save_engram(title, content):
        saved.append("engram")

    return "Saved to: " + ", ".join(saved) if saved else "Save failed."


def _write_wiki(title: str, content: str) -> str | None:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    slug_words = re.sub(r"[^\w\s]", "", title.lower()).split()[:6]
    slug = "_".join(slug_words) or "untitled"
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    dest = WIKI_DIR / f"{slug}.md"
    dest.write_text(
        f"# {title}\n\n_Auto-saved · {ts}_\n\n{content}\n",
        encoding="utf-8",
    )
    _embed_wiki_node(dest)
    return str(dest)


def _embed_wiki_node(path: Path) -> None:
    """Embed the node into the 'wiki' ChromaDB collection so it is immediately
    retrievable via semantic search (the feedback loop). Best-effort: the .md
    file is already persisted, so an embedding failure is non-fatal."""
    try:
        from infra.rag.src.ingest import ingest_file
        ingest_file(path)
    except Exception:
        pass


def _save_engram(title: str, content: str) -> bool:
    try:
        proc = subprocess.run(
            [ENGRAM_BIN, "save", title, content, "--project", ENGRAM_PROJECT],
            capture_output=True, text=True, timeout=8,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
