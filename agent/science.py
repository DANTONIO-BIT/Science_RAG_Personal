#!/usr/bin/env python3
"""
Science Agent — CLI entry point.

USAGE
-----
  # Ask a question (uses RAG + local/cloud LLM routing automatically)
  python agent/science.py "What does the knowledge base say about Hfq in Salmonella?"

  # Ingest a single file
  python agent/science.py --ingest path/to/paper.pdf

  # Ingest a whole directory
  python agent/science.py --ingest data/public/papers/inbox/

  # Interactive REPL (multi-turn session)
  python agent/science.py --interactive

  # Only search public collection (never touches private data)
  python agent/science.py --collection public "How do R-loops affect transcription?"

  # Show retrieved context without LLM synthesis
  python agent/science.py --context-only "Hfq binding mechanism"

  # Force cloud LLM (Claude API) for deep synthesis
  python agent/science.py --cloud "Generate a hypothesis about RNase H and Salmonella virulence"

  # Check knowledge base status
  python agent/science.py --status

SETUP
-----
  pip install -r infra/rag/requirements.txt
  ollama pull bge-m3
  ollama serve
  # Optional (for cloud fallback):
  export ANTHROPIC_API_KEY=sk-ant-...

INGEST INITIAL CORPUS
---------------------
  python infra/rag/run_ingest.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Repo root → sys.path so `infra.rag.src` is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"

logging.basicConfig(
    level=logging.WARNING,  # quiet by default; use --verbose for debug
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("science-agent")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are a scientific research assistant. Answer precisely, cite sources."


def _print_result(result: dict, verbose: bool = False) -> None:
    """Pretty-print a route() result to stdout."""
    confidence = result["confidence"]
    llm = result["llm_used"]
    sources = result["context_sources"]
    wiki = result["wiki_written"]

    print("\n" + "─" * 60)
    print(result["response"])
    print("─" * 60)

    meta_parts = [f"confidence: {confidence:.3f}", f"llm: {llm}", f"sources: {sources}"]
    if wiki:
        meta_parts.append(f"wiki → {Path(wiki).name}")
    print("  ".join(meta_parts))

    if verbose and wiki:
        print(f"\n📝 Wiki node written: {wiki}")


def _check_status() -> None:
    """Print knowledge base collection statistics."""
    try:
        import chromadb
        import yaml
    except ImportError as e:
        print(f"❌ Missing dependency: {e}. Run: pip install -r infra/rag/requirements.txt")
        sys.exit(1)

    cfg_path = REPO_ROOT / "infra/rag/config/config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    persist_path = REPO_ROOT / cfg["chroma"]["persist_directory"]

    if not persist_path.exists():
        print("⚠️  ChromaDB not initialized yet. Run: python infra/rag/run_ingest.py")
        return

    client = chromadb.PersistentClient(path=str(persist_path))

    print("\n📊 Knowledge Base Status")
    print("─" * 40)
    for col_name in ["public", "private"]:
        try:
            col = client.get_collection(col_name)
            count = col.count()
            label = "🔓 public " if col_name == "public" else "🔒 private"
            print(f"  {label}  {count:>6} chunks")
        except Exception:
            print(f"  ({'🔓' if col_name == 'public' else '🔒'}) {col_name:<8}  (empty / not created)")

    wiki_dir = REPO_ROOT / cfg["wiki"]["output_dir"]
    wiki_nodes = list(wiki_dir.glob("*.md")) if wiki_dir.exists() else []
    print(f"  📖 wiki nodes   {len(wiki_nodes):>6} files")
    print()


def _do_ingest(path: Path, verbose: bool) -> None:
    """Ingest a file or directory."""
    try:
        from infra.rag.src.ingest import ingest_file
    except ImportError as e:
        print(f"❌ Import error: {e}")
        sys.exit(1)

    if path.is_dir():
        supported = {".pdf", ".md", ".txt", ".fasta", ".vcf", ".bed", ".tsv", ".csv", ".html"}
        files = [f for f in path.rglob("*") if f.is_file() and f.suffix.lower() in supported]
        if not files:
            print(f"No supported files found in {path}")
            sys.exit(0)
        print(f"Ingesting {len(files)} files from {path}…")
        ok = err = 0
        for i, f in enumerate(files, 1):
            try:
                chunks = ingest_file(f)
                if verbose:
                    print(f"  [{i}/{len(files)}] ✅ {f.name} → {chunks} chunks")
                else:
                    print(f"  ✅ {f.name} ({chunks} chunks)")
                ok += 1
            except Exception as e:
                print(f"  ❌ {f.name}: {e}")
                err += 1
        print(f"\nDone: {ok} ingested, {err} failed.")
    else:
        if not path.exists():
            print(f"❌ File not found: {path}")
            sys.exit(1)
        try:
            chunks = ingest_file(path)
            print(f"✅ {path.name} → {chunks} chunks ingested")
        except Exception as e:
            print(f"❌ {path.name}: {e}")
            sys.exit(1)


def _do_query(
    query: str,
    collection: str | None,
    context_only: bool,
    force_cloud: bool,
    verbose: bool,
) -> None:
    """Run a single query through the RAG + routing pipeline."""
    try:
        from infra.rag.src import query_public, query_private, query_full, compute_confidence, format_context
        from infra.rag.src.router import route, PrivacyError
    except ImportError as e:
        print(f"❌ Import error: {e}\nRun: pip install -r infra/rag/requirements.txt")
        sys.exit(1)

    # Collection-scoped retrieval (bypasses routing, raw context only)
    if context_only or collection:
        q_fn = {"public": query_public, "private": query_private}.get(collection or "full", query_full)
        results = q_fn(query, n_results=5)
        confidence = compute_confidence(results)
        print(format_context(results))
        print(f"\nconfidence: {confidence:.3f}  |  hits: {len(results)}")
        return

    # Full routing pipeline
    if force_cloud:
        # Skip routing — call cloud directly with public context
        from infra.rag.src import query_public, format_context
        try:
            import anthropic
        except ImportError:
            print("❌ anthropic SDK required for --cloud. Run: pip install anthropic")
            sys.exit(1)

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("❌ ANTHROPIC_API_KEY not set")
            sys.exit(1)

        results = query_public(query, n_results=8)
        context_block = format_context(results)
        system = _load_system_prompt()
        prompt = f"{context_block}\n\nQuestion: {query}"

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()
        print("\n" + "─" * 60)
        print(response)
        print("─" * 60)
        print(f"  llm: cloud (forced)  |  sources: public")
        return

    # Standard routing
    try:
        result = route(query)
        _print_result(result, verbose=verbose)
    except PrivacyError as e:
        print(f"\n⚠️  Privacy gate: {e}")
        answer = input("Send to cloud with public context only? [y/N]: ").strip().lower()
        if answer == "y":
            result = route(query, confirmed_cloud=True)
            _print_result(result, verbose=verbose)
        else:
            print("Aborted. Use --collection public to restrict to public knowledge only.")
    except RuntimeError as e:
        # Ollama not running
        print(f"\n⚠️  {e}")
        if os.getenv("ANTHROPIC_API_KEY"):
            answer = input("Fall back to Claude API? [y/N]: ").strip().lower()
            if answer == "y":
                _do_query(query, collection, context_only, force_cloud=True, verbose=verbose)
        sys.exit(1)


def _interactive_loop(verbose: bool) -> None:
    """Multi-turn REPL — delegates to ReAct harness for native tool-calling."""
    # Add agent/ dir to path so harness can import its sibling tools/
    agent_dir = Path(__file__).parent
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))

    try:
        from harness import run_interactive
    except ImportError as e:
        print(f"❌ Harness import error: {e}\nRun: pip install -r infra/rag/requirements.txt")
        sys.exit(1)

    run_interactive(_load_system_prompt())


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Science Agent — RAG-powered research assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Positional query (optional)
    parser.add_argument("query", nargs="?", help="Scientific question to answer")

    # Modes
    parser.add_argument("--ingest", metavar="PATH", help="Ingest a file or directory into the knowledge base")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start interactive REPL")
    parser.add_argument("--status", action="store_true", help="Show knowledge base collection stats")

    # Query options
    parser.add_argument(
        "--collection", choices=["public", "private"], default=None,
        help="Restrict retrieval to a single collection"
    )
    parser.add_argument("--context-only", action="store_true", help="Show raw retrieved context, skip LLM")
    parser.add_argument("--cloud", action="store_true", help="Force Claude API (skip local LLM)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output (show wiki paths, debug info)")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        _check_status()
        return

    if args.ingest:
        _do_ingest(Path(args.ingest), verbose=args.verbose)
        return

    if args.interactive:
        _interactive_loop(verbose=args.verbose)
        return

    if not args.query:
        parser.print_help()
        sys.exit(0)

    _do_query(
        query=args.query,
        collection=args.collection,
        context_only=args.context_only,
        force_cloud=args.cloud,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
