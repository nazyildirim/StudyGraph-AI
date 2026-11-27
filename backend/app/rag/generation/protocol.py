"""LLMClient Protocol for provider-independent answer generation."""

from __future__ import annotations

from typing import Protocol

from app.rag.generation.types import LLMRequest, LLMResponse


class LLMClient(Protocol):
    """Contract implemented by real (Ollama) and backup/test LLM clients."""

    @property
    def model_name(self) -> str: ...

    def generate(self, request: LLMRequest) -> LLMResponse: ...
