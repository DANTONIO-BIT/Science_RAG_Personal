#!/usr/bin/env python3
"""
scripts/backup.py — Exporta TODO el conocimiento custodiado para migración.

Crea un bundle .tar.gz autocontenido con todo lo que define tu sistema pero
que NO vive en git: documentos, notas privadas, salidas NGS, el corpus de
projects/, los nodos wiki generados con el tiempo, la config local con
secretos (.env, opencode.json) y la MEMORIA ENGRAM (estado cognitivo).

Pensado para ejecutarse ANTES de desinstalar/borrar la máquina vieja:
captura el estado completo en un solo archivo. Luego, en la máquina nueva:
    bash scripts/bootstrap.sh <bundle>.tar.gz   → restaura + reindexa.

Incluye manifest.json con sha256 + tamaño por archivo (restore.py lo verifica).

Qué se respalda (por defecto):
    data/public/  data/private/  data/ngs/  wiki/auto_generated/  projects/
    + .env  opencode.json                 (secretos / config local)
    + engram/engram-export.json           (memoria Engram completa, vía `engram export`)

NOTA Engram: `engram export` vuelca TODA la memoria (todos los proyectos de
Engram en esta máquina), no solo "science-agent". En una máquina nueva la DB
está vacía, así que el import reconstruye el estado sin conflictos.

Se EXCLUYE el ruido reconstruible: .git, __pycache__, node_modules, .venv,
chroma_db (el vector store se reconstruye al reindexar, no se copia).

⚠ El bundle contiene datos privados, secretos y memoria → guárdalo cifrado/offline.

Uso:
    python scripts/backup.py                    # todo → backups/knowledge-<fecha>.tar.gz
    python scripts/backup.py --out ruta.tar.gz  # destino explícito
    python scripts/backup.py --no-secrets       # excluye .env / opencode.json
    python scripts/backup.py --no-private       # excluye data/private/ (para compartir)
    python scripts/backup.py --no-engram        # excluye la memoria Engram
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directorios que constituyen el conocimiento custodiado (relativos al repo).
INCLUDE_DIRS = [
    "data/public",
    "data/private",
    "data/ngs",
    "wiki/auto_generated",
    "projects",
]

# Secretos / config local (archivos sueltos en la raíz del repo).
SECRET_FILES = [".env", "opencode.json"]

# Ruido reconstruible que nunca debe entrar al bundle.
EXCLUDE_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv",
    ".opencode", "indexed_cache", "chroma_db",
}

ENGRAM_BIN = shutil.which("engram") or "/usr/local/bin/engram"
ENGRAM_ARCNAME = "engram/engram-export.json"

MANIFEST_NAME = "manifest.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _excluded(path: Path) -> bool:
    return bool(set(path.parts) & EXCLUDE_DIR_NAMES) or path.name == ".DS_Store"


def _collect(include_dirs: list[str], secret_files: list[str]) -> list[Path]:
    files: list[Path] = []
    for rel in include_dirs:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and not _excluded(f):
                files.append(f)
    for rel in secret_files:
        f = REPO_ROOT / rel
        if f.is_file():
            files.append(f)
    return sorted(set(files))


def _export_engram(dest: Path) -> bool:
    """Run `engram export <dest>`. Returns True if a non-empty JSON was produced."""
    if not Path(ENGRAM_BIN).exists():
        return False
    try:
        subprocess.run(
            [ENGRAM_BIN, "export", str(dest)],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return dest.exists() and dest.stat().st_size > 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Exporta data/ + projects/ + wiki + secretos + memoria Engram para migración.")
    ap.add_argument("--out", help="Ruta del bundle .tar.gz de salida")
    ap.add_argument("--no-private", action="store_true",
                    help="Excluye data/private/ (para compartir solo lo público)")
    ap.add_argument("--no-secrets", action="store_true",
                    help="Excluye .env / opencode.json")
    ap.add_argument("--no-engram", action="store_true",
                    help="Excluye la memoria Engram")
    args = ap.parse_args()

    include = [d for d in INCLUDE_DIRS if not (args.no_private and d == "data/private")]
    secrets = [] if args.no_secrets else SECRET_FILES

    files = _collect(include, secrets)
    # (source_path, arcname-en-el-tar)
    entries: list[tuple[Path, str]] = [
        (f, f.relative_to(REPO_ROOT).as_posix()) for f in files
    ]

    # Memoria Engram → export a un temporal y se mete al tar como engram/engram-export.json
    engram_tmp: Path | None = None
    if not args.no_engram:
        engram_tmp = Path(tempfile.gettempdir()) / f"engram-export-{os.getpid()}.json"
        if _export_engram(engram_tmp):
            entries.append((engram_tmp, ENGRAM_ARCNAME))
        else:
            engram_tmp = None
            print("  (Engram no disponible o vacío — bundle sin memoria Engram)")

    if not entries:
        print("Nada que respaldar.", file=sys.stderr)
        return 1

    manifest = {
        "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "includes": include + secrets + ([ENGRAM_ARCNAME] if engram_tmp else []),
        "files": {},
    }
    total_bytes = 0
    for src, arc in entries:
        size = src.stat().st_size
        total_bytes += size
        manifest["files"][arc] = {"sha256": _sha256(src), "bytes": size}

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = Path.cwd() / out
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = REPO_ROOT / "backups" / f"knowledge-{stamp}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(out, "w:gz") as tar:
            info = tarfile.TarInfo(MANIFEST_NAME)
            data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            for src, arc in entries:
                tar.add(src, arcname=arc)
    finally:
        if engram_tmp and engram_tmp.exists():
            engram_tmp.unlink()

    def _count(pred) -> int:
        return sum(1 for r in manifest["files"] if pred(r))

    mb = total_bytes / (1024 * 1024)
    print(f"Bundle creado: {out}")
    print(f"  {len(entries)} archivos · {mb:.1f} MB")
    print(f"  data/public:   {_count(lambda r: r.startswith('data/public/'))}")
    print(f"  data/private:  {_count(lambda r: r.startswith('data/private/'))}")
    print(f"  data/ngs:      {_count(lambda r: r.startswith('data/ngs/'))}")
    print(f"  projects:      {_count(lambda r: r.startswith('projects/'))}")
    print(f"  wiki nodes:    {_count(lambda r: r.startswith('wiki/auto_generated/'))}")
    if secrets:
        print(f"  secretos:      {_count(lambda r: r in SECRET_FILES)}  (.env / opencode.json)")
    if engram_tmp:
        print("  engram:        memoria completa incluida (engram export)")
    if secrets or engram_tmp:
        print("  ⚠ El bundle contiene SECRETOS, datos privados y memoria → guárdalo cifrado/offline.")
    print(f"\nRestaurar en otra máquina:  bash scripts/bootstrap.sh {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
