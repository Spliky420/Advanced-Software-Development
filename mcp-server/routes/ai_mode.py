import os

from flask import Blueprint, request
from openai import OpenAI


ai_mode_bp = Blueprint("ai_mode", __name__)

# Ollama's OpenAI-compatible endpoint, on the shared compose network --
# never a commercial API (see CLAUDE.md's LLM access rules).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

# The client requires a non-empty api_key even though Ollama ignores it.
_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


@ai_mode_bp.post("/ai/ask")
def ai_ask():
    """Baseline 'AI mode': the model answers directly, with no tool access
    and no Python-computed figures behind it -- contrast with /mcp/*,
    where every number traces back to a teammate's backend. This route is
    the demonstration of the failure mode CLAUDE.md's arithmetic rule
    guards against (see the qwen2.5:0.5b misreading example), not a
    substitute for MCP mode.
    """
    question = request.form.get("question", "").strip()
    if not question:
        return "<p>question is required.</p>", 400

    try:
        completion = _client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": question}],
        )
        answer = completion.choices[0].message.content
    except Exception as exc:
        return f"<p>AI mode failed.</p><pre>{exc}</pre>", 503

    return f"<h3>AI Mode</h3><p>{answer}</p>", 200
