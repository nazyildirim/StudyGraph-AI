"""Local Ollama LLMClient using existing `httpx` dependency.

Security & reliability:
- Enforces local loopback URL (`127.0.0.1`, `localhost`, `::1`) so course
  materials and student questions are never sent to external hosts.
- Disables Qwen3 thinking output (`think: false`) and defensively strips any
  `<think>...</think>` block so internal reasoning is never shown to students.
- Uses Ollama structured JSON `format` schema, but NEVER trusts raw output:
  validates JSON syntax, field types, and non-empty answer in application code.
- Lazy HTTP usage: importing or constructing `OllamaLLMClient` never connects
  to Ollama.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from app.rag.generation.errors import (
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)
from app.rag.generation.types import LLMRequest, LLMResponse

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


class OllamaLLMClient:
    """Local Ollama `/api/chat` client implementing `LLMClient`."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model_name: str = "qwen3:4b",
        timeout_seconds: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        parsed = urlparse(base_url.strip())
        if parsed.scheme not in {"http", "https"} or (
            (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS
        ):
            raise ValueError(
                "OllamaLLMClient only permits local loopback URLs "
                "(127.0.0.1, localhost, ::1)."
            )
        if not model_name or not model_name.strip():
            raise ValueError("model_name must not be blank.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0.")

        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name.strip()
        self._timeout = timeout_seconds
        self._injected_client = http_client

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": self._model_name,
            "stream": False,
            "think": False,
            "format": dict(request.response_schema),
            "options": {
                "num_ctx": request.context_window,
                "num_predict": request.max_output_tokens,
                "temperature": request.temperature,
            },
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }

        try:
            if self._injected_client is not None:
                response = self._injected_client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    timeout=self._timeout,
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        f"{self._base_url}/api/chat",
                        json=payload,
                    )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self._timeout}s."
            ) from error
        except (httpx.ConnectError, httpx.HTTPStatusError, httpx.RequestError) as error:
            raise LLMConnectionError(
                f"Failed to communicate with local Ollama service ({type(error).__name__})."
            ) from error

        try:
            outer = response.json()
        except ValueError as error:
            raise LLMInvalidResponseError("Ollama returned non-JSON HTTP body.") from error

        message = outer.get("message") if isinstance(outer, dict) else None
        raw_content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise LLMInvalidResponseError("Ollama returned an empty message content.")

        return parse_structured_llm_json(raw_content, model_name=self._model_name)


def parse_structured_llm_json(raw_content: str, *, model_name: str) -> LLMResponse:
    """Strictly parse and validate the structured JSON returned by an LLM."""
    cleaned = _THINK_TAG_RE.sub("", raw_content).strip()
    try:
        parsed = json.loads(cleaned)
    except ValueError as error:
        raise LLMInvalidResponseError("LLM content is not valid JSON.") from error

    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError("LLM JSON payload must be an object.")

    sufficient = parsed.get("sufficient_context")
    answer = parsed.get("answer")
    citations = parsed.get("citations")

    if not isinstance(sufficient, bool):
        raise LLMInvalidResponseError("Field 'sufficient_context' must be a boolean.")
    if not isinstance(answer, str) or not answer.strip():
        raise LLMInvalidResponseError("Field 'answer' must be a non-empty string.")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise LLMInvalidResponseError("Field 'citations' must be a list of strings.")

    clean_answer = _THINK_TAG_RE.sub("", answer).strip()
    if not clean_answer:
        raise LLMInvalidResponseError("Answer is empty after stripping thinking tags.")

    return LLMResponse(
        sufficient_context=sufficient,
        answer=clean_answer,
        cited_source_ids=tuple(citations),
        model_name=model_name,
        is_fallback=False,
    )
