#!/usr/bin/env python3
"""
Initial corpus ingest — batch-loads PDFs from projects/ into the 'public' ChromaDB collection.

Usage (from repo root):
    python infra/rag/run_ingest.py                           # ingest default corpus
    python infra/rag/run_ingest.py --path data/public/       # ingest a specific directory
    python infra/rag/run_ingest.py --file path/to/paper.pdf  # ingest a single file

Prerequisites:
    1. pip install -r infra/rag/requirements.txt
    2. ollama serve  (bge-m3 model must be pulled: ollama pull bge-m3)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path so `from infra.rag.src import ...` works
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from infra.rag.src.ingest import ingest_file  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "logs" / "ingest.log", mode="a"),
    ],
)
logger = logging.getLogger("run_ingest")

# Default corpus: existing papers from science_projects_IA_ML
DEFAULT_CORPUS = REPO_ROOT / "projects/science_projects_IA_ML/metaanalisis_pipeline/PDF_content"

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".fasta", ".vcf", ".bed", ".tsv", ".csv", ".html"}


def ingest_directory(directory: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Recursively ingest all supported files in a directory.
    Returns (success_count, error_count).
    """
    files = [
        f for f in directory.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        logger.warning("No supported files found in %s", directory)
        return 0, 0

    logger.info("Found %d files to ingest in %s", len(files), directory)

    success = 0
    errors = 0
    start = time.time()

    for i, fpath in enumerate(files, 1):
        if dry_run:
            logger.info("[DRY RUN] Would ingest: %s", fpath.name)
            continue
        try:
            chunks = ingest_file(fpath)
            logger.info("[%d/%d] ✅  %s → %d chunks", i, len(files), fpath.name, chunks)
            success += 1
        except ValueError as e:
            logger.warning("[%d/%d] ⚠️  Skipped %s: %s", i, len(files), fpath.name, e)
            errors += 1
        except Exception as e:
            logger.error("[%d/%d] ❌  Failed %s: %s", i, len(files), fpath.name, e)
            errors += 1

    elapsed = time.time() - start
    logger.info(
        "Done. %d ingested, %d skipped/errored. Elapsed: %.1fs",
        success, errors, elapsed,
    )
    return success, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest scientific documents into the RAG knowledge base."
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="Directory to ingest recursively (default: projects corpus)"
    )
    parser.add_argument(
        "--file", type=Path, default=None,
        help="Ingest a single file"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be ingested without actually running"
    )
    args = parser.parse_args()

    # Ensure logs dir exists
    (Path(__file__).parent / "logs").mkdir(parents=True, exist_ok=True)

    if args.file:
        if not args.file.exists():
            logger.error("File not found: %s", args.file)
            sys.exit(1)
        try:
            chunks = ingest_file(args.file)
            logger.info("✅  %s → %d chunks", args.file.name, chunks)
        except Exception as e:
            logger.error("❌  %s: %s", args.file.name, e)
            sys.exit(1)
        return

    directory = args.path or DEFAULT_CORPUS
    if not directory.exists():
        logger.error("Directory not found: %s", directory)
        sys.exit(1)

    logger.info("=== RAG Ingest Starting ===")
    logger.info("Source: %s", directory)
    success, errors = ingest_directory(directory, dry_run=args.dry_run)

    if not args.dry_run:
        logger.info("=== Ingest Complete: %d ok, %d failed ===", success, errors)
        if errors > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
