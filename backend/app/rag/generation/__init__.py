"""RAG generation package (LLMClient, Ollama, Extractive fallback, PromptBuilder, CitationValidator)."""

from app.rag.generation.citation_validator import CitationValidator
from app.rag.generation.errors import (
    CitationValidationError,
    LLMConnectionError,
    LLMError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)
from app.rag.generation.extractive_client import (
    EXTRACTIVE_MODEL_NAME,
    EXTRACTIVE_NOTICE,
    ExtractiveLLMClient,
)
from app.rag.generation.ollama_client import OllamaLLMClient, parse_structured_llm_json
from app.rag.generation.prompt_builder import DEFAULT_MAX_CONTEXT_CHARS, PromptBuilder
from app.rag.generation.protocol import LLMClient
from app.rag.generation.types import (
    AnswerMode,
    AssistantAnswer,
    BuiltPrompt,
    LLMRequest,
    LLMResponse,
    SourceEntry,
    ValidatedSource,
)

__all__ = [
    "AnswerMode",
    "AssistantAnswer",
    "BuiltPrompt",
    "CitationValidationError",
    "CitationValidator",
    "DEFAULT_MAX_CONTEXT_CHARS",
    "EXTRACTIVE_MODEL_NAME",
    "EXTRACTIVE_NOTICE",
    "ExtractiveLLMClient",
    "LLMClient",
    "LLMConnectionError",
    "LLMError",
    "LLMInvalidResponseError",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "OllamaLLMClient",
    "PromptBuilder",
    "SourceEntry",
    "ValidatedSource",
    "parse_structured_llm_json",
]
