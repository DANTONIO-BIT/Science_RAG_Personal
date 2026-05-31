#!/usr/bin/env python3
"""
scripts/restore.py — Restaura el conocimiento custodiado y reconstruye el índice.

Extrae un bundle creado por backup.py (data/ + projects/ + nodos wiki + secretos
.env/opencode.json + memoria Engram), verifica integridad con el manifest
(sha256), importa la memoria Engram y reindexa ChromaDB DESDE CERO, de modo que
en una máquina nueva el sistema vuelve a quedar idéntico — incluidos el corpus de
projects/, los nodos wiki y el estado cognitivo de Engram.

Reindex limpio = borra infra/rag/data/chroma_db/ y vuelve a ejecutar
infra.rag.src.reingest_all, evitando chunks huérfanos de archivos eliminados.

Uso:
    python scripts/restore.py bundle.tar.gz        # extrae + verifica + reindexa
    python scripts/restore.py --reindex-only       # solo reindexa el data/ actual
    python scripts/restore.py bundle.tar.gz --no-reindex
    python scripts/restore.py bundle.tar.gz --no-verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = REPO_ROOT / "infra" / "rag" / "data" / "chroma_db"
MANIFEST_NAME = "manifest.json"

# Prefijos / archivos permitidos dentro del bundle — defensa anti path-traversal.
ALLOWED_PREFIXES = ("data/", "wiki/auto_generated/", "projects/", "engram/")
ALLOWED_FILES = (".env", "opencode.json")

ENGRAM_BIN = shutil.which("engram") or "/usr/local/bin/engram"
ENGRAM_EXPORT = REPO_ROOT / "engram" / "engram-export.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _safe_members(tar: tarfile.TarFile):
    """Devuelve solo miembros seguros (sin rutas absolutas ni '..')."""
    for m in tar.getmembers():
        name = m.name
        if m.name == MANIFEST_NAME:
            yield m
            continue
        p = Path(name)
        if p.is_absolute() or ".." in p.parts:
            print(f"  ! omito miembro inseguro: {name}", file=sys.stderr)
            continue
        if not (name.startswith(ALLOWED_PREFIXES) or name in ALLOWED_FILES):
            print(f"  ! omito miembro fuera de alcance: {name}", file=sys.stderr)
            continue
        yield m


def extract_bundle(bundle: Path, verify: bool) -> int:
    if not bundle.exists():
        print(f"ERROR: bundle no encontrado: {bundle}", file=sys.stderr)
        return -1

    with tarfile.open(bundle, "r:gz") as tar:
        members = list(_safe_members(tar))
        # Lee manifest si está presente.
        manifest = None
        for m in members:
            if m.name == MANIFEST_NAME:
                f = tar.extractfile(m)
                if f:
                    manifest = json.loads(f.read().decode("utf-8"))
                break

        data_members = [m for m in members if m.name != MANIFEST_NAME]
        print(f"-> extrayendo {len(data_members)} archivos en {REPO_ROOT}")
        tar.extractall(REPO_ROOT, members=data_members)

    if verify and manifest:
        print("-> verificando integridad (sha256)")
        bad = 0
        for rel, meta in manifest.get("files", {}).items():
            target = REPO_ROOT / rel
            if not target.exists():
                print(f"  ! falta: {rel}")
                bad += 1
            elif _sha256(target) != meta["sha256"]:
                print(f"  ! hash no coincide: {rel}")
                bad += 1
        if bad:
            print(f"   AVISO: {bad} archivo(s) con problemas de integridad.")
        else:
            print(f"   OK {len(manifest.get('files', {}))} archivos verificados.")
    elif verify:
        print("   (bundle sin manifest — omito verificación)")

    return len(data_members)


def import_engram() -> None:
    """Importa la memoria Engram del bundle (engram/engram-export.json), si existe.

    Best-effort: `engram import` falla con error de constraint si la DB ya tiene
    datos, así que está pensado para una DB limpia (máquina nueva). No aborta el
    restore — solo avisa."""
    if not ENGRAM_EXPORT.exists():
        return
    if not Path(ENGRAM_BIN).exists():
        print(f"  ! Engram no instalado — memoria queda en {ENGRAM_EXPORT} (sin importar)")
        return
    print("-> importando memoria Engram")
    try:
        r = subprocess.run(
            [ENGRAM_BIN, "import", str(ENGRAM_EXPORT)],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            print("   OK memoria Engram importada")
        else:
            print("   AVISO: engram import devolvió error (¿la DB ya tenía datos?):")
            print(f"   {(r.stderr or r.stdout).strip()[:200]}")
            print("   El import limpio solo aplica en una máquina nueva (DB Engram vacía).")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"   AVISO: no se pudo importar Engram: {e}")


def reindex() -> int:
    """Borra el vector store y reconstruye desde data/ + projects/ + wiki/."""
    if CHROMA_DIR.exists():
        print(f"-> borrando índice anterior: {CHROMA_DIR}")
        shutil.rmtree(CHROMA_DIR)

    print("-> reindexando ChromaDB desde las fuentes (puede tardar)")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from infra.rag.src.reingest_all import main as reingest_main
    except Exception as e:
        print(f"ERROR: no se pudo importar reingest_all: {e}", file=sys.stderr)
        print("       ¿Instalaste deps?  .venv/bin/pip install -r infra/rag/requirements.txt",
              file=sys.stderr)
        return 1
    reingest_main()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Restaura conocimiento y reconstruye el índice.")
    ap.add_argument("bundle", nargs="?", help="Ruta al bundle .tar.gz (omitir con --reindex-only)")
    ap.add_argument("--reindex-only", action="store_true",
                    help="No extrae nada; solo reconstruye el índice del data/ actual")
    ap.add_argument("--no-reindex", action="store_true", help="Solo extrae; no reindexa")
    ap.add_argument("--no-verify", action="store_true", help="Omite verificación sha256")
    args = ap.parse_args()

    if args.reindex_only:
        return reindex()

    if not args.bundle:
        ap.error("indica un bundle .tar.gz o usa --reindex-only")

    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        # Busca primero en cwd, luego en backups/.
        cand = Path.cwd() / bundle
        bundle = cand if cand.exists() else (REPO_ROOT / "backups" / args.bundle)

    n = extract_bundle(bundle, verify=not args.no_verify)
    if n < 0:
        return 1

    import_engram()

    if args.no_reindex:
        print("Listo (sin reindexar). Ejecuta luego: python scripts/restore.py --reindex-only")
        return 0
    return reindex()


if __name__ == "__main__":
    sys.exit(main())
