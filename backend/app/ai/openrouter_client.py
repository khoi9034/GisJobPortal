from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import AIProviderError, MissingAPIKeyError, TextGenerator

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def configured_key(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    return bool(lowered) and "placeholder" not in lowered and "replace_with" not in lowered


class OpenRouterClient(TextGenerator):
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int = 30):
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        if not configured_key(self.api_key):
            raise MissingAPIKeyError("OPENROUTER_API_KEY is not configured")
        self.model = model or os.getenv("AI_MODEL", "openrouter/pony-alpha")
        self.timeout = timeout

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://gis-job-portal.vercel.app",
                "X-OpenRouter-Title": "GIS Apply Copilot",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise AIProviderError(f"OpenRouter request failed with HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"OpenRouter request failed: {exc.__class__.__name__}") from exc

        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("OpenRouter response did not include message content") from exc

