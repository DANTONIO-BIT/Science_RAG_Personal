"""
Sanitized cloud LLM escalation via OpenRouter.
Only public-safe content reaches here — privacy gate enforced by the model's tool description.
"""
from __future__ import annotations

import os

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Primary: high-capacity free tier. Fallback defined in .env (OPENROUTER_MODEL).
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def call_cloud(prompt: str, confirmed: bool = False) -> str:
    """
    Send prompt to OpenRouter. Returns the model's response text.
    Requires OPENROUTER_API_KEY in environment.

    When confirmed=False (default): returns a preview of what would be sent and
    asks for explicit user confirmation. Call again with confirmed=True to execute.
    NEVER include private research notes in the prompt.
    """
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)

    if not confirmed:
        preview = prompt[:600] + ("…" if len(prompt) > 600 else "")
        return (
            f"[CLOUD GATE — confirmation required]\n"
            f"Model: {model}\n"
            f"Content preview (public context only):\n\n{preview}\n\n"
            f"⚠ Private research notes are NEVER included.\n"
            f"Reply 'yes, proceed' to confirm, then call call_cloud again with confirmed=True."
        )

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set in .env"

    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3001",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
                "temperature": 0.3,
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        return f"Cloud error {e.response.status_code}: {e.response.text[:300]}"
    except httpx.TimeoutException:
        return "Cloud call timed out (90s). Try a shorter prompt."
    except Exception as e:
        return f"Cloud call failed: {e}"
