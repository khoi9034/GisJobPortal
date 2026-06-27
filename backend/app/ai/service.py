from __future__ import annotations

import os

from ..paths import load_backend_env
from .base import AIProviderError, MissingAPIKeyError
from .openrouter_client import OpenRouterClient, configured_key


def ai_status() -> dict[str, object]:
    load_backend_env()
    provider = os.getenv("AI_PROVIDER", "openrouter")
    model = os.getenv("AI_MODEL", "openrouter/pony-alpha")
    configured = provider == "openrouter" and configured_key(os.getenv("OPENROUTER_API_KEY"))
    return {
        "provider": provider,
        "model": model,
        "configured": configured,
        "mode": "pony_alpha" if configured else "template_fallback",
    }


def generate_text(system_prompt: str, user_prompt: str, temperature: float = 0.4) -> tuple[str, str]:
    status = ai_status()
    if status["mode"] != "pony_alpha":
        return "", "template_fallback"
    try:
        client = OpenRouterClient(model=str(status["model"]))
        return client.generate_text(system_prompt, user_prompt, temperature), "pony_alpha"
    except (AIProviderError, MissingAPIKeyError):
        return "", "template_fallback"
