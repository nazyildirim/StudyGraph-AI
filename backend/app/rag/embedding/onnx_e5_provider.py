"""Local ONNX Runtime implementation for `intfloat/multilingual-e5-small`.

Official model specification (verified against Hugging Face revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, MIT license):
- `hidden_size`: 384
- `max_position_embeddings`: 512
- `1_Pooling/config.json`: `pooling_mode_mean_tokens = True` (attention-mask mean)
- E5 prefix convention: `"passage: "` for documents, `"query: "` for queries
- L2-normalized output vectors so cosine similarity equals dot product.

Lazy loading: importing this module or instantiating `OnnxE5EmbeddingProvider`
never touches disk or network until an embedding or token-count call is made.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import threading
from typing import Any

import numpy as np

from app.rag.embedding.errors import (
    InvalidEmbeddingInputError,
    InvalidEmbeddingVectorError,
    ModelNotFoundError,
    TokenLimitExceededError,
)
from app.rag.embedding.validation import l2_normalize_matrix

DEFAULT_MODEL_NAME = "intfloat/multilingual-e5-small"
DEFAULT_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
DEFAULT_EMBEDDING_DIM = 384
DEFAULT_MAX_TOKENS = 512
EXPECTED_MODEL_SHA256 = (
    "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"
)
EXPECTED_TOKENIZER_SHA256 = (
    "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"
)

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


class OnnxE5EmbeddingProvider:
    """CPU ONNX Runtime embedding provider for multilingual-e5-small."""

    def __init__(
        self,
        model_dir: Path | str,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        dimension: int = DEFAULT_EMBEDDING_DIM,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        batch_size: int = 32,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be > 0.")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be > 0.")
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0.")

        self._model_dir = Path(model_dir)
        self._model_name = model_name
        self._dimension = dimension
        self._max_tokens = max_tokens
        self._batch_size = batch_size

        self._lock = threading.Lock()
        self._tokenizer: Any | None = None
        self._session: Any | None = None
        self._input_names: frozenset[str] = frozenset()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def is_loaded(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    def count_tokens(self, text: str, *, is_query: bool = False) -> int:
        """Return exact token count including E5 prefix and special tokens."""
        cleaned = _validate_non_empty_text(text)
        prefixed = f"{QUERY_PREFIX if is_query else PASSAGE_PREFIX}{cleaned}"
        tokenizer = self._ensure_tokenizer_loaded()
        encoding = tokenizer.encode(prefixed)
        return len(encoding.ids)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            raise InvalidEmbeddingInputError("texts must not be empty.")
        prefixed = [
            f"{PASSAGE_PREFIX}{_validate_non_empty_text(text)}"
            for text in texts
        ]
        return self._embed_prefixed(prefixed)

    def embed_query(self, text: str) -> list[float]:
        cleaned = _validate_non_empty_text(text)
        vectors = self._embed_prefixed([f"{QUERY_PREFIX}{cleaned}"])
        return vectors[0]

    def _ensure_tokenizer_loaded(self) -> Any:
        if self._tokenizer is not None:
            return self._tokenizer
        with self._lock:
            if self._tokenizer is not None:
                return self._tokenizer
            tokenizer_path = self._model_dir / "tokenizer.json"
            if not tokenizer_path.is_file():
                raise ModelNotFoundError(
                    f"Tokenizer file not found at {tokenizer_path}. "
                    f"Expected local {self._model_name} files."
                )
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(tokenizer_path))
            # Never silently truncate inputs; callers must split or handle errors.
            tokenizer.no_truncation()
            tokenizer.no_padding()
            self._tokenizer = tokenizer
            return self._tokenizer

    def _ensure_session_loaded(self) -> tuple[Any, Any]:
        tokenizer = self._ensure_tokenizer_loaded()
        if self._session is not None:
            return tokenizer, self._session
        with self._lock:
            if self._session is not None:
                return tokenizer, self._session
            model_path = self._model_dir / "model.onnx"
            if not model_path.is_file():
                raise ModelNotFoundError(
                    f"ONNX model file not found at {model_path}. "
                    f"Expected local {self._model_name} files."
                )
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            )
            session = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._input_names = frozenset(inp.name for inp in session.get_inputs())
            self._session = session
            return tokenizer, self._session

    def _embed_prefixed(self, prefixed_texts: Sequence[str]) -> list[list[float]]:
        tokenizer, session = self._ensure_session_loaded()
        encodings = tokenizer.encode_batch(list(prefixed_texts))

        for encoding in encodings:
            token_count = len(encoding.ids)
            if token_count > self._max_tokens:
                raise TokenLimitExceededError(token_count, self._max_tokens)

        all_vectors: list[list[float]] = []
        for start in range(0, len(encodings), self._batch_size):
            batch = encodings[start : start + self._batch_size]
            batch_max_len = max(len(enc.ids) for enc in batch)

            input_ids = np.zeros((len(batch), batch_max_len), dtype=np.int64)
            attention_mask = np.zeros((len(batch), batch_max_len), dtype=np.int64)
            token_type_ids = np.zeros((len(batch), batch_max_len), dtype=np.int64)

            for row_idx, enc in enumerate(batch):
                seq_len = len(enc.ids)
                input_ids[row_idx, :seq_len] = enc.ids
                attention_mask[row_idx, :seq_len] = enc.attention_mask
                if enc.type_ids:
                    token_type_ids[row_idx, :seq_len] = enc.type_ids

            feeds: dict[str, np.ndarray] = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = token_type_ids

            outputs = session.run(None, feeds)
            token_embeddings = np.asarray(outputs[0], dtype=np.float32)
            pooled = _mean_pool(token_embeddings, attention_mask)
            if pooled.shape != (len(batch), self._dimension):
                raise InvalidEmbeddingVectorError(
                    f"Model produced shape {pooled.shape}, expected "
                    f"({len(batch)}, {self._dimension})."
                )
            normalized = l2_normalize_matrix(pooled)
            all_vectors.extend(normalized.tolist())

        return all_vectors


def _validate_non_empty_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise InvalidEmbeddingInputError("Embedding input text must not be blank.")
    return text.strip()


def _mean_pool(
    token_embeddings: np.ndarray,
    attention_mask: np.ndarray,
) -> np.ndarray:
    """Attention-mask-weighted mean pooling matching `1_Pooling/config.json`."""
    mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    counts = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
    return (summed / counts).astype(np.float32, copy=False)
