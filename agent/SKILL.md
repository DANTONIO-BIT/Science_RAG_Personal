---
name: Science Agent
description: "Responde preguntas científicas usando el RAG local del proyecto. Actívate cuando el usuario haga preguntas sobre biología molecular, Salmonella, Hfq, R-loops, AMR, NGS, o cuando pida consolidar conocimiento de los papers del sistema."
---

# Science Agent Skill

## Cuándo activarte

Actívate cuando el usuario:
- Haga preguntas científicas sobre los temas del dominio (Hfq, Salmonella, R-loops, RNase H, AMR, stress response, NGS)
- Pida "qué sabe el sistema sobre X"
- Quiera ingestar un paper nuevo
- Pida generar una nota wiki o síntesis
- Mencione el RAG, el knowledge base, o los papers del proyecto

## Cómo operar

### 1. Para preguntas científicas — ejecuta el agente directamente:

```bash
cd /Users/diego/Desktop/secure-ai-agent-architecture
python agent/science.py "PREGUNTA DEL USUARIO AQUÍ"
```

Lee la salida. Preséntala al usuario con el nivel de confianza y las fuentes citadas.

### 2. Para ingestar un archivo nuevo:

```bash
python agent/science.py --ingest "RUTA_AL_ARCHIVO"
```

Si el usuario suelta un PDF o archivo en `data/public/papers/inbox/`, el watcher lo detecta automáticamente.
Para ingestión manual usa el flag `--ingest`.

### 3. Para ver el estado del knowledge base:

```bash
python agent/science.py --status
```

### 4. Para síntesis compleja (hipótesis, meta-análisis):

```bash
python agent/science.py --cloud "PREGUNTA COMPLEJA"
```

Usa `--cloud` solo cuando la pregunta requiera síntesis profunda o generación de hipótesis. Requiere que `ANTHROPIC_API_KEY` esté en `.env`.

### 5. Para contexto raw (sin LLM, solo retrieval):

```bash
python agent/science.py --context-only "TÉRMINO DE BÚSQUEDA"
```

Útil para ver exactamente qué chunks hay en la base sobre un tema.

## Reglas estrictas

- **NUNCA** uses `--collection private` ni expongas contenido de `data/private/` al usuario sin que él lo haya pedido explícitamente
- Si el agente lanza un `PrivacyError`, pregúntale al usuario antes de proceder
- Si Ollama no está corriendo, avisa al usuario en lugar de fallar silenciosamente
- No inventes resultados si el RAG devuelve baja confianza — di explícitamente "La base de conocimiento no cubre esto suficientemente"

## Contexto del proyecto

- Repo: `/Users/diego/Desktop/secure-ai-agent-architecture`
- RAG config: `infra/rag/config/config.yaml`
- Corpus inicial (56 papers): `projects/science_projects_IA_ML/metaanalisis_pipeline/PDF_content/`
- Inbox para papers nuevos: `data/public/papers/inbox/`
- Wiki generada: `wiki/auto_generated/`
- Embeddings: bge-m3 via Ollama (puerto 11434)
- LLM local: qwen2.5:7b via Ollama
- Cloud fallback: Claude API (necesita ANTHROPIC_API_KEY)

## Setup si aún no está listo

```bash
# 1. Instalar dependencias Python
pip install -r infra/rag/requirements.txt

# 2. Levantar Ollama
ollama pull bge-m3
ollama pull qwen2.5:7b
ollama serve

# 3. Ingestar el corpus inicial (una sola vez)
python infra/rag/run_ingest.py

# 4. Verificar
python agent/science.py --status
```
