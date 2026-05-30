"""
Re-ingest one-shot: reconstruye ChromaDB desde las fuentes en disco.

Recorre los directorios vigilados (data/ + projects/) e ingesta cada archivo
soportado con su ruteo de coleccion correcto. Excluye ruido (node_modules,
.opencode, .git, __pycache__, ocultos).

Uso:  .venv/bin/python -m infra.rag.src.reingest_all
"""
from __future__ import annotations

import sys
from pathlib import Path

from .ingest import ingest_file, _resolve_collection

REPO_ROOT = Path(__file__).parent.parent.parent.parent

WATCH_DIRS = [
    REPO_ROOT / "data" / "public",
    REPO_ROOT / "data" / "private",
    REPO_ROOT / "data" / "ngs",
    REPO_ROOT / "wiki" / "auto_generated",   # re-embed synthesis nodes (feedback loop)
    REPO_ROOT / "projects",
]

SUPPORTED = {".pdf", ".md", ".txt", ".fasta", ".fa", ".fna", ".faa",
             ".vcf", ".bed", ".tsv", ".csv", ".html"}

EXCLUDE_DIRS = {"node_modules", ".opencode", ".git", "__pycache__",
                ".venv", "indexed_cache"}


def _excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    # cualquier componente oculto (empieza con .)
    return any(p.startswith(".") and p not in {".", ".."} for p in path.parts)


def collect() -> list[Path]:
    files: list[Path] = []
    for root in WATCH_DIRS:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in SUPPORTED:
                continue
            if _excluded(f):
                continue
            files.append(f)
    return sorted(set(files))


def main() -> None:
    files = collect()
    print(f"Archivos a ingestar: {len(files)}", flush=True)
    totals: dict[str, int] = {}
    ok = err = 0
    for f in files:
        try:
            col = _resolve_collection(f)
            n = ingest_file(f)
            totals[col] = totals.get(col, 0) + n
            ok += 1
            print(f"  OK [{col:7}] {f.name} -> {n} chunks", flush=True)
        except Exception as e:
            err += 1
            print(f"  ERR {f.name}: {e}", flush=True)
    print(f"\nResumen: {ok} OK, {err} errores", flush=True)
    for col, n in sorted(totals.items()):
        print(f"  coleccion '{col}': {n} chunks", flush=True)


if __name__ == "__main__":
    sys.exit(main())
