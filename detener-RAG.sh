#!/bin/bash
#
# detener-RAG.sh — Detiene el watcher de ingesta
# Uso: ./detener-RAG.sh

WATCHER_PID=$(pgrep -f "infra.rag.src.watcher" 2>/dev/null | head -1)

if [ -z "$WATCHER_PID" ]; then
    echo "Watcher no esta corriendo."
    exit 0
fi

kill "$WATCHER_PID"
echo "Watcher detenido (PID: $WATCHER_PID)"
