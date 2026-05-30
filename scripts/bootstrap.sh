#!/bin/bash
#
# scripts/bootstrap.sh — Reconstruye el sistema completo en una máquina nueva.
#
# El repo de GitHub trae SOLO la arquitectura (código + config). Este script
# recrea el entorno y el esqueleto de data/, y opcionalmente restaura tu
# conocimiento custodiado (data/ + nodos wiki) desde un bundle de migración.
#
# Uso:
#   bash scripts/bootstrap.sh                          # entorno + esqueleto (sin datos)
#   bash scripts/bootstrap.sh path/al/bundle.tar.gz    # entorno + restaura datos + reindexa
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="$REPO_ROOT/.venv"
BUNDLE="${1:-}"

echo "========================================="
echo "  BOOTSTRAP  ·  $REPO_ROOT"
echo "========================================="

# 1. Entorno Python aislado
if [ ! -x "$VENV/bin/python" ]; then
    echo "-> creando venv con $PYTHON_BIN"
    "$PYTHON_BIN" -m venv "$VENV"
fi
PY="$VENV/bin/python"
echo "   OK venv ($("$PY" --version 2>&1))"
"$PY" -m pip install --upgrade pip >/dev/null
echo "-> instalando dependencias Python"
"$PY" -m pip install -r infra/rag/requirements.txt

# 2. Dependencias del gateway (Node)
if command -v npm >/dev/null 2>&1; then
    echo "-> npm install (gateway)"
    npm install --silent
else
    echo "   AVISO: npm no encontrado — omito gateway"
fi

# 3. Esqueleto de datos custodiados (no versionado)
echo "-> recreando esqueleto data/ + wiki/"
mkdir -p \
    data/public/papers/inbox data/public/papers/indexed \
    data/public/references/bacteria data/public/references/eukaryotes data/public/references/transposons \
    data/private/hypotheses data/private/notes data/private/synthesis \
    data/ngs/reports data/ngs/results data/ngs/sequences \
    wiki/auto_generated infra/rag/input infra/rag/logs backups

# 4. Variables de entorno
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "   .env creado desde .env.example — EDÍTALO con tu OPENROUTER_API_KEY"
    else
        echo "   AVISO: crea .env manualmente (falta .env.example)"
    fi
fi

# 5. Ollama + modelos locales
if command -v ollama >/dev/null 2>&1; then
    echo "-> verificando modelos Ollama (bge-m3, qwen3:8b)"
    ollama pull bge-m3
    ollama pull qwen3:8b
else
    echo "   AVISO: ollama no instalado."
    echo "          Instálalo desde https://ollama.com y luego: ollama pull bge-m3 qwen3:8b"
fi

# 6. Restaurar conocimiento + reindexar
if [ -n "$BUNDLE" ]; then
    echo "-> restaurando bundle de conocimiento: $BUNDLE"
    "$PY" scripts/restore.py "$BUNDLE"
else
    echo ""
    echo "Entorno listo. Para cargar conocimiento:"
    echo "  1) copia tus archivos en data/  (o restaura un bundle)"
    echo "  2) reindexa:   $PY scripts/restore.py --reindex-only"
    echo "  o restaura un bundle:   $PY scripts/restore.py mi_bundle.tar.gz"
fi

echo "========================================="
echo "  BOOTSTRAP COMPLETO"
echo "========================================="
