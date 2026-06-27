from __future__ import annotations

from abc import ABC, abstractmethod


class AIProviderError(RuntimeError):
    pass


class MissingAPIKeyError(AIProviderError):
    pass


class TextGenerator(ABC):
    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
        raise NotImplementedError

