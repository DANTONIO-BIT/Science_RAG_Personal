#!/bin/bash
#
# iniciar-RAG.sh — Inicia el watcher de ingesta automática
# Uso: ./iniciar-RAG.sh
#
# Usa el venv aislado (.venv, Python 3.9 + chromadb 1.5.0) — stack probada en M3.
# NO usa el Python global para no acoplarse con otros proyectos (knowledge_base).
# Monitorea projects/*/inbox/, projects/*/private/, data/ y data/ngs/.
# Archivos nuevos → embed → ChromaDB; PDFs de inbox/ → indexed/ tras ingestar.

REPO_ROOT="$HOME/Desktop/secure-ai-agent-architecture"
PYTHON="$REPO_ROOT/.venv/bin/python"
LOG_DIR="$REPO_ROOT/infra/rag/logs"

echo "========================================="
echo "  INICIANDO RAG WATCHER"
echo "========================================="

# 0. Verificar venv
if [ ! -x "$PYTHON" ]; then
    echo ""
    echo "ERROR: venv no encontrado en $PYTHON"
    echo "   Crealo con: /Library/Developer/CommandLineTools/usr/bin/python3.9 -m venv .venv"
    echo "   Luego: .venv/bin/pip install -r infra/rag/requirements.txt"
    exit 1
fi
echo "   OK venv ($($PYTHON --version 2>&1))"

# 1. Verificar Ollama
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo ""
    echo "ERROR: Ollama no responde en localhost:11434"
    echo "   Asegurate de tener Ollama corriendo"
    exit 1
fi
echo "   OK Ollama disponible"

# 2. Verificar si ya corre
WATCHER_PID=$(pgrep -f "infra.rag.src.watcher" 2>/dev/null | head -1)
if [ -n "$WATCHER_PID" ]; then
    echo ""
    echo "AVISO: Watcher ya esta corriendo (PID: $WATCHER_PID)"
    echo "   Para detenerlo: kill $WATCHER_PID"
    echo ""
    echo "========================================="
    exit 0
fi

# 3. Crear directorio de logs
mkdir -p "$LOG_DIR"

# 4. Arrancar watcher en background
cd "$REPO_ROOT"
nohup $PYTHON -m infra.rag.src.watcher > "$LOG_DIR/watcher.log" 2>&1 &

PID=$!
sleep 2

# 5. Verificar arranque
if ps -p $PID > /dev/null 2>&1; then
    echo ""
    echo "OK Watcher iniciado"
    echo "   PID: $PID"
    echo "   Logs: $LOG_DIR/watcher.log"
    echo ""
    echo "========================================="
    echo "  RAG WATCHER ACTIVO"
    echo "========================================="
else
    echo ""
    echo "ERROR: No se pudo iniciar el watcher"
    echo "   Revisa: $LOG_DIR/watcher.log"
    exit 1
fi
