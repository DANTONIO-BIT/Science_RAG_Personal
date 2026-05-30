#!/usr/bin/env python3
"""
scripts/backup.py — Empaqueta el conocimiento custodiado para migración.

Crea un bundle .tar.gz autocontenido con TODO lo que define tu sistema pero
que NO vive en git: documentos, notas privadas, salidas NGS y — importante —
los nodos wiki que el agente fue generando con el tiempo.

Incluye un manifest.json con sha256 + tamaño de cada archivo, de modo que
restore.py pueda verificar integridad al reinstalar en otra máquina.

Qué se respalda:
    data/public/   data/private/   data/ngs/   wiki/auto_generated/

Uso:
    python scripts/backup.py                       # -> backups/knowledge-<fecha>.tar.gz
    python scripts/backup.py --out ruta.tar.gz     # destino explícito
    python scripts/backup.py --no-private          # excluye data/private/ del bundle
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directorios que constituyen el conocimiento custodiado (relativos al repo).
INCLUDE_DIRS = [
    "data/public",
    "data/private",
    "data/ngs",
    "wiki/auto_generated",
]

MANIFEST_NAME = "manifest.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _collect(include_dirs: list[str]) -> list[Path]:
    files: list[Path] = []
    for rel in include_dirs:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.name != ".DS_Store":
                files.append(f)
    return sorted(set(files))


def main() -> int:
    ap = argparse.ArgumentParser(description="Empaqueta data/ + nodos wiki para migración.")
    ap.add_argument("--out", help="Ruta del bundle .tar.gz de salida")
    ap.add_argument("--no-private", action="store_true",
                    help="Excluye data/private/ (para compartir solo lo público)")
    args = ap.parse_args()

    include = [d for d in INCLUDE_DIRS if not (args.no_private and d == "data/private")]

    files = _collect(include)
    if not files:
        print("Nada que respaldar: data/ y wiki/auto_generated/ están vacíos.", file=sys.stderr)
        return 1

    # Manifest con integridad por archivo.
    manifest = {
        "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "includes": include,
        "files": {},
    }
    total_bytes = 0
    for f in files:
        rel = f.relative_to(REPO_ROOT).as_posix()
        size = f.stat().st_size
        total_bytes += size
        manifest["files"][rel] = {"sha256": _sha256(f), "bytes": size}

    # Destino.
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = Path.cwd() / out
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = REPO_ROOT / "backups" / f"knowledge-{stamp}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Escribe el tar: manifest primero, luego los archivos con su ruta relativa al repo.
    with tarfile.open(out, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
        for f in files:
            tar.add(f, arcname=f.relative_to(REPO_ROOT).as_posix())

    wiki_n = sum(1 for r in manifest["files"] if r.startswith("wiki/auto_generated/"))
    priv_n = sum(1 for r in manifest["files"] if r.startswith("data/private/"))
    mb = total_bytes / (1024 * 1024)
    print(f"Bundle creado: {out}")
    print(f"  {len(files)} archivos · {mb:.1f} MB")
    print(f"  nodos wiki: {wiki_n} · archivos privados: {priv_n}")
    print(f"\nRestaurar en otra máquina:  python scripts/restore.py {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
