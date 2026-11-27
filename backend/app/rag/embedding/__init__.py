"""Embedding provider package (Protocol, ONNX E5, validation, token splitting)."""

from app.rag.embedding.errors import (
    EmbeddingError,
    EmbeddingModelMismatchError,
    InvalidEmbeddingInputError,
    InvalidEmbeddingVectorError,
    ModelNotFoundError,
    TokenLimitExceededError,
)
from app.rag.embedding.onnx_e5_provider import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_REVISION,
    EXPECTED_MODEL_SHA256,
    EXPECTED_TOKENIZER_SHA256,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    OnnxE5EmbeddingProvider,
)
from app.rag.embedding.protocol import EmbeddingProvider
from app.rag.embedding.token_splitter import enforce_token_limit
from app.rag.embedding.validation import (
    deserialize_vector,
    l2_normalize_matrix,
    serialize_vector,
    validate_vector,
)

__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_MODEL_REVISION",
    "EXPECTED_MODEL_SHA256",
    "EXPECTED_TOKENIZER_SHA256",
    "EmbeddingError",
    "EmbeddingModelMismatchError",
    "EmbeddingProvider",
    "InvalidEmbeddingInputError",
    "InvalidEmbeddingVectorError",
    "ModelNotFoundError",
    "OnnxE5EmbeddingProvider",
    "PASSAGE_PREFIX",
    "QUERY_PREFIX",
    "TokenLimitExceededError",
    "deserialize_vector",
    "enforce_token_limit",
    "l2_normalize_matrix",
    "serialize_vector",
    "validate_vector",
]
