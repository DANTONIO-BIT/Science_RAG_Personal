"""
ReAct harness — native tool-calling loop via Ollama /api/chat.

The model decides when to call tools. No pre-fetching.
Pattern: generate → tool_call? execute+inject+loop : stream text+done.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).parent.parent
AGENT_DIR = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENT_DIR))

from tools.memory import search_memory   # noqa: E402
from tools.insight import save_insight   # noqa: E402
from tools.cloud import call_cloud       # noqa: E402

logger = logging.getLogger(__name__)

CONFIG_PATH = REPO_ROOT / "infra/rag/config/config.yaml"
_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


TOOL_REGISTRY = {
    "search_memory": search_memory,
    "save_insight": save_insight,
    "call_cloud": call_cloud,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Search the research knowledge base: scientific papers (ChromaDB), "
                "private hypotheses and notes, auto-generated wiki synthesis nodes, "
                "and Engram session memory. "
                "Call this when you need factual grounding from the corpus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["all", "public", "private", "wiki", "engram"],
                        "description": "Memory source to search. Omit for all sources.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_insight",
            "description": (
                "Persist an important synthesis or finding to long-term memory "
                "(wiki node + Engram). Call after producing an answer worth retaining "
                "for future sessions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short descriptive title (5–10 words)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Insight content to save (plain text or markdown)",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_cloud",
            "description": (
                "Escalate to a cloud LLM (OpenRouter) when local knowledge is clearly "
                "insufficient for complex synthesis. The user is asked to confirm before "
                "anything is sent (handled automatically by the harness). "
                "NEVER include private research notes — public context only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Complete prompt for the cloud model",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]


def _stream_call(messages: list[dict], cfg: dict) -> tuple[str, list]:
    """
    Streaming /api/chat call. Prints text tokens live as they arrive.
    Returns (accumulated_text, tool_calls).
    tool_calls == [] means the model produced a final text answer.
    """
    local = cfg["llm"]["local"]
    url = f"{local['base_url']}/api/chat"

    payload = {
        "model": local["model"],
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "stream": True,
        "options": {
            "temperature": local.get("temperature", 0.2),
            # 4096 covers qwen3 thinking phase (300-800 tokens) + full scientific response
            "num_predict": 4096,
        },
    }

    text_parts: list[str] = []
    final_tool_calls: list = []
    thinking_shown = False

    try:
        with httpx.stream(
            "POST", url, json=payload,
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                chunk = json.loads(raw)
                msg = chunk.get("message", {})

                # Show thinking indicator once — user knows the model is reasoning
                if not thinking_shown and msg.get("thinking"):
                    print("[thinking...]", flush=True)
                    thinking_shown = True

                token = msg.get("content", "")
                if token:
                    print(token, end="", flush=True)
                    text_parts.append(token)
                if chunk.get("done"):
                    final_tool_calls = msg.get("tool_calls") or []
                    break
    except httpx.ConnectError:
        raise RuntimeError(
            "Ollama is not running. Start it with: ollama serve\n"
            f"Then ensure the model is available: ollama pull {local['model']}"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}")

    return "".join(text_parts), final_tool_calls


def _call_cloud_gated(fn_args: dict) -> str:
    """
    Enforce the two-step cloud privacy gate with the human in the loop.

    The local model never controls confirmation: the harness shows the OpenRouter
    preview (call_cloud confirmed=False), asks the user on stdin, and only then
    executes (confirmed=True). This is what keeps the model from self-approving a
    cloud escalation during the autonomous ReAct loop.
    """
    prompt = fn_args.get("prompt", "")
    if not prompt:
        print("✗  empty prompt", flush=True)
        return "call_cloud error: empty prompt."

    preview = call_cloud(prompt=prompt, confirmed=False)
    print("needs confirmation", flush=True)
    print("\n" + preview)

    try:
        answer = input("\n  Send to cloud? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer in {"y", "yes", "s", "si", "sí", "proceed", "ok"}:
        print("  [call_cloud] executing ", end="", flush=True)
        try:
            result = call_cloud(prompt=prompt, confirmed=True)
            print("✓", flush=True)
            return result
        except Exception as exc:
            print(f"✗  {exc}", flush=True)
            logger.warning("call_cloud execution failed: %s", exc)
            return f"Cloud call failed: {exc}"

    print("  declined by user", flush=True)
    return ("User declined the cloud escalation. Do not retry call_cloud for this "
            "query — answer from local knowledge or state what is missing.")


def run_once(
    query: str,
    system_prompt: str,
    history: list[dict],
) -> tuple[str, dict]:
    """
    Run a single user query through the ReAct loop.

    Returns:
        (response_text, metadata)
        metadata keys: tools_called, iterations, warning (optional)
    """
    cfg = _load_config()

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": query})

    tools_called: list[dict] = []

    for iteration in range(8):
        text, tool_calls = _stream_call(messages, cfg)

        if not tool_calls:
            if text:
                print()  # newline after streamed output
            return text, {"tools_called": tools_called, "iterations": iteration + 1}

        # Append assistant turn with tool_calls
        messages.append({
            "role": "assistant",
            "content": text,
            "tool_calls": tool_calls,
        })

        # Execute each tool call and inject results
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"]["arguments"]
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}

            print(f"\n  [{fn_name}] ", end="", flush=True)

            tool_fn = TOOL_REGISTRY.get(fn_name)
            if fn_name == "call_cloud":
                # Human-in-the-loop privacy gate: the harness (not the model) owns
                # confirmation, so the model can never self-approve a cloud send
                # inside the ReAct loop.
                result = _call_cloud_gated(fn_args)
            elif tool_fn:
                try:
                    result = tool_fn(**fn_args)
                    print("✓", flush=True)
                except Exception as exc:
                    result = f"Tool error: {exc}"
                    logger.warning("Tool %s failed: %s", fn_name, exc)
                    print(f"✗  {exc}", flush=True)
            else:
                result = f"Unknown tool: {fn_name}"
                print("✗  unknown", flush=True)

            tools_called.append({"tool": fn_name, "args": fn_args})
            messages.append({"role": "tool", "content": str(result)})

    # Safety: 8 iterations reached without final answer
    return text, {"tools_called": tools_called, "iterations": 8, "warning": "max_iterations"}


def run_interactive(system_prompt: str) -> None:
    """
    Multi-turn REPL with ReAct tool-calling.
    Maintains conversation history across turns.
    """
    cfg = _load_config()
    model_name = cfg["llm"]["local"]["model"]

    print(f"Science Agent  |  {model_name}  |  tools: search_memory · save_insight · call_cloud")
    print("Commands: exit · status\n")

    history: list[dict] = []

    try:
        import readline  # noqa: F401  — enables arrow keys + history
    except ImportError:
        pass

    while True:
        try:
            query = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("Exiting.")
            break
        if query.lower() == "status":
            print(_status_summary())
            continue

        print()
        try:
            response, meta = run_once(query, system_prompt, history)
        except RuntimeError as e:
            print(f"\n[error] {e}")
            continue

        if meta.get("tools_called"):
            names = " + ".join(t["tool"] for t in meta["tools_called"])
            print(f"\n  tools: {names}")
        if meta.get("warning"):
            print(f"\n  warning: {meta['warning']}")

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": response})


def _status_summary() -> str:
    try:
        import chromadb
        cfg = _load_config()
        persist = REPO_ROOT / cfg["chroma"]["persist_directory"]
        lines = ["\nKnowledge Base Status:"]
        if persist.exists():
            client = chromadb.PersistentClient(path=str(persist))
            for name in ("public", "private", "wiki"):
                try:
                    count = client.get_collection(name).count()
                    lines.append(f"  {name:<10} {count:>6} chunks")
                except Exception:
                    lines.append(f"  {name:<10}  (empty / not created)")
        else:
            lines.append("  ChromaDB not initialized — run: python infra/rag/run_ingest.py")

        wiki_dir = REPO_ROOT / cfg["wiki"]["output_dir"]
        nodes = len(list(wiki_dir.glob("*.md"))) if wiki_dir.exists() else 0
        lines.append(f"  wiki       {nodes:>6} nodes")
        return "\n".join(lines)
    except Exception as e:
        return f"Status unavailable: {e}"
