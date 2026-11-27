"""Real ONNX multilingual-e5-small smoke tests (opt-in via env flag).

Normal unit tests never require the downloaded 470 MB model or internet.
Run explicitly with:
    STUDYGRAPH_RUN_REAL_MODEL_TESTS=1 ../.venv/bin/python -m pytest tests/rag/test_onnx_e5_real_model.py -v
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import numpy as np
import pytest

from app.rag.embedding import (
    DEFAULT_EMBEDDING_DIM,
    EXPECTED_MODEL_SHA256,
    EXPECTED_TOKENIZER_SHA256,
    OnnxE5EmbeddingProvider,
    TokenLimitExceededError,
)

pytestmark = pytest.mark.real_model

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "models" / "multilingual-e5-small"

if os.environ.get("STUDYGRAPH_RUN_REAL_MODEL_TESTS") != "1":
    pytest.skip(
        "Set STUDYGRAPH_RUN_REAL_MODEL_TESTS=1 to run real ONNX model smoke tests.",
        allow_module_level=True,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@pytest.fixture(scope="module")
def e5_provider() -> OnnxE5EmbeddingProvider:
    return OnnxE5EmbeddingProvider(MODEL_DIR)


def test_downloaded_model_files_match_official_sha256() -> None:
    assert _sha256(MODEL_DIR / "model.onnx") == EXPECTED_MODEL_SHA256
    assert _sha256(MODEL_DIR / "tokenizer.json") == EXPECTED_TOKENIZER_SHA256


def test_real_model_dimension_norm_batch_and_token_limit(
    e5_provider: OnnxE5EmbeddingProvider,
) -> None:
    single = e5_provider.embed_documents(["C dilinde işaretçiler bellek adresi tutar."])[0]
    batch = e5_provider.embed_documents(
        [
            "C dilinde işaretçiler bellek adresi tutar.",
            "Python for döngüsü liste elemanlarını sırayla gezer.",
        ]
    )
    assert len(single) == DEFAULT_EMBEDDING_DIM == 384
    assert math.isclose(math.sqrt(sum(x * x for x in single)), 1.0, rel_tol=1e-4)
    assert np.allclose(single, batch[0], atol=1e-4)

    # Exceeding 512 tokens must raise TokenLimitExceededError (never silent truncation).
    oversized = " ".join(["algoritma"] * 600)
    with pytest.raises(TokenLimitExceededError) as exc_info:
        e5_provider.embed_documents([oversized])
    assert exc_info.value.token_count > 512


def test_real_model_semantic_ranking_turkish_and_english(
    e5_provider: OnnxE5EmbeddingProvider,
) -> None:
    passages = [
        "C dilinde pointer (işaretçi), başka bir değişkenin bellek adresini saklar. int *p = &x; ifadesi x değişkeninin adresini p işaretçisine atar.",
        "Python programlama dilinde for ve while döngüleri yinelenen işlemleri gerçekleştirmek için kullanılır. range() fonksiyonu sayı dizisi üretir.",
        "İşletim sistemlerinde process bağımsız bellek alanına sahip bir çalışan programdır; thread ise aynı process içindeki hafif yürütme birimidir.",
        "Domates çorbası yapmak için taze domatesler rendelenir, tereyağı ve un ile kavrularak kısık ateşte kaynatılır.",
    ]
    doc_vecs = np.asarray(e5_provider.embed_documents(passages), dtype=np.float32)

    queries_and_expected = [
        ("C dilinde işaretçi ve bellek adresi nasıl kullanılır?", 0),
        ("How do pointers store memory addresses in C?", 0),
        ("Python döngüleri nasıl çalışır?", 1),
        ("What is the difference between a process and a thread in operating systems?", 2),
    ]

    for query, expected_idx in queries_and_expected:
        q_vec = np.asarray(e5_provider.embed_query(query), dtype=np.float32)
        scores = doc_vecs @ q_vec
        best_idx = int(np.argmax(scores))
        assert best_idx == expected_idx, f"query={query!r} scores={scores.tolist()}"
        # Relevant passage must score clearly higher than the unrelated cooking text.
        assert float(scores[expected_idx]) > float(scores[3]) + 0.05


def test_real_model_calibrated_threshold_and_session_reuse(
    e5_provider: OnnxE5EmbeddingProvider,
) -> None:
    """Verify calibrated 0.81 threshold accepts relevant TR/EN/code queries,
    rejects completely unrelated queries, and reuses the loaded ONNX session.
    """
    from app.rag.retrieval import DEFAULT_SEMANTIC_MIN_SCORE

    assert DEFAULT_SEMANTIC_MIN_SCORE == 0.81
    session_before = e5_provider._session

    corpus = [
        "C dilinde işaretçi (pointer) başka bir değişkenin bellek adresini saklar. malloc ile dinamik bellek ayrılır.",
        "Python programlama dilinde for ve while döngüleri yinelenen işlemleri gerçekleştirmek için kullanılır.",
        "Yığın (Stack) veri yapısı LIFO (Last-In First-Out) prensibiyle çalışır; push ekler, pop çıkarır.",
    ]
    doc_vecs = np.asarray(e5_provider.embed_documents(corpus), dtype=np.float32)

    positive_queries = [
        "C dilinde işaretçi ve malloc nasıl kullanılır?",
        "How do pointers and malloc work in C?",
        "Python for döngüsü nasıl çalışır?",
        "Yığın LIFO push pop nedir?",
    ]
    for q in positive_queries:
        top1 = float(np.max(doc_vecs @ np.asarray(e5_provider.embed_query(q), dtype=np.float32)))
        assert top1 >= DEFAULT_SEMANTIC_MIN_SCORE, f"Unexpected FN for {q!r}: {top1}"

    unrelated_queries = [
        "Mercimek çorbası tarifi ve pişirme süresi nedir?",
        "İstanbul hava durumu yarın yağmurlu mu olacak?",
        "Futbol maçında ofsayt kuralı ne zaman uygulanır?",
    ]
    for q in unrelated_queries:
        top1 = float(np.max(doc_vecs @ np.asarray(e5_provider.embed_query(q), dtype=np.float32)))
        assert top1 < DEFAULT_SEMANTIC_MIN_SCORE, f"Unexpected FP for {q!r}: {top1}"

    # ONNX session object must be reused across all queries (never reloaded).
    assert e5_provider._session is session_before
