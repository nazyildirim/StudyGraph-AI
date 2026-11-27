"""Float32 vector validation, L2 normalization, and BYTEA serialization."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.rag.embedding.errors import InvalidEmbeddingVectorError

_FLOAT32_LE = np.dtype("<f4")


def validate_vector(
    vector: Sequence[float] | np.ndarray,
    expected_dim: int,
) -> np.ndarray:
    """Validate 1-D float32 vector: exact dimension, finite, non-zero norm."""
    if expected_dim <= 0:
        raise ValueError("expected_dim must be > 0.")
    try:
        arr = np.asarray(vector, dtype=_FLOAT32_LE)
    except (TypeError, ValueError) as error:
        raise InvalidEmbeddingVectorError("Vector cannot be converted to float32.") from error

    if arr.ndim != 1 or arr.shape[0] != expected_dim:
        raise InvalidEmbeddingVectorError(
            f"Expected 1-D vector of dimension {expected_dim}, got shape {arr.shape}."
        )
    if not np.all(np.isfinite(arr)):
        raise InvalidEmbeddingVectorError(
            "Vector contains NaN or infinite values."
        )
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm == 0.0:
        raise InvalidEmbeddingVectorError("Vector must have a non-zero L2 norm.")
    return arr


def l2_normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    """Validate and L2-normalize a 2-D float32 matrix row-wise."""
    arr = np.asarray(matrix, dtype=_FLOAT32_LE)
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise InvalidEmbeddingVectorError(
            f"Expected non-empty 2-D matrix, got shape {arr.shape}."
        )
    if not np.all(np.isfinite(arr)):
        raise InvalidEmbeddingVectorError(
            "Embedding matrix contains NaN or infinite values."
        )
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0.0):
        raise InvalidEmbeddingVectorError(
            "Embedding matrix contains a zero-norm vector."
        )
    return (arr / norms).astype(_FLOAT32_LE, copy=False)


def serialize_vector(
    vector: Sequence[float] | np.ndarray,
    expected_dim: int,
) -> bytes:
    """Validate and serialize a vector to little-endian IEEE-754 float32 bytes."""
    arr = validate_vector(vector, expected_dim)
    return arr.tobytes()


def deserialize_vector(raw: bytes, expected_dim: int) -> np.ndarray:
    """Deserialize float32 bytes and verify length, finiteness, and norm."""
    if expected_dim <= 0:
        raise ValueError("expected_dim must be > 0.")
    expected_bytes = expected_dim * 4
    if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) != expected_bytes:
        raise InvalidEmbeddingVectorError(
            f"Expected {expected_bytes} bytes for dim={expected_dim}, "
            f"got {len(raw) if isinstance(raw, (bytes, bytearray, memoryview)) else type(raw).__name__}."
        )
    arr = np.frombuffer(raw, dtype=_FLOAT32_LE).copy()
    return validate_vector(arr, expected_dim)
