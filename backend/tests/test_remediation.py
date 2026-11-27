"""Remediation tests covering HIGH-1, MEDIUM-1, MEDIUM-2, MEDIUM-4, and LOW-3."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.api.middleware import UploadBodyLimitMiddleware
from app.core.config import get_cors_origins_for_app
from app.rag.domain import RetrievedChunk
from app.rag.generation.prompt_builder import PromptBuilder, detect_question_language
from app.rag.generation.types import AnswerMode


# ----------------------------------------------------------- HIGH-1 ASGI guard
def _run_asgi_upload(
    *,
    headers: list[tuple[bytes, bytes]],
    body_chunks: list[bytes],
    max_body_bytes: int = 100,
    path: str = "/api/v1/courses/1/materials/upload",
) -> tuple[int, bool]:
    downstream_called = False

    async def dummy_app(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True
        while True:
            msg = await receive()
            if not msg.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = UploadBodyLimitMiddleware(dummy_app, max_body_bytes=max_body_bytes)
    sent: list[dict] = []
    idx = 0

    async def receive():
        nonlocal idx
        if idx < len(body_chunks):
            chunk = body_chunks[idx]
            idx += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": idx < len(body_chunks),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
    }
    asyncio.run(mw(scope, receive, send))
    status_code = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status_code, downstream_called


def test_high1_content_length_fast_reject_never_invokes_downstream() -> None:
    status_code, called = _run_asgi_upload(
        headers=[(b"content-length", b"500")],
        body_chunks=[b"x" * 500],
        max_body_bytes=100,
    )
    assert status_code == 413
    assert called is False  # rejected BEFORE multipart parser or route runs


def test_high1_missing_content_length_chunked_stream_rejected_with_413() -> None:
    status_code, _ = _run_asgi_upload(
        headers=[],
        body_chunks=[b"a" * 60, b"b" * 60],
        max_body_bytes=100,
    )
    assert status_code == 413


def test_high1_forged_small_content_length_rejected_when_stream_exceeds_limit() -> None:
    status_code, _ = _run_asgi_upload(
        headers=[(b"content-length", b"10")],
        body_chunks=[b"a" * 60, b"b" * 60],
        max_body_bytes=100,
    )
    assert status_code == 413


def test_high1_non_upload_route_is_unaffected() -> None:
    status_code, called = _run_asgi_upload(
        headers=[(b"content-length", b"500")],
        body_chunks=[b"x" * 500],
        max_body_bytes=100,
        path="/api/v1/courses/1/assistant",
    )
    assert status_code == 200 and called is True


# ----------------------------------------------------------- MEDIUM-2 CORS env
def test_medium2_cors_reads_dotenv_and_respects_env_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\n",
        encoding="utf-8",
    )

    # 1. Reads from .env when process env is unset
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert get_cors_origins_for_app(env_file=env_file) == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # 2. Process env overrides .env
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:4173")
    assert get_cors_origins_for_app(env_file=env_file) == ["http://localhost:4173"]

    # 3. Missing .env falls back safely to defaults
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert get_cors_origins_for_app(env_file=tmp_path / "missing.env") == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 4. Wildcard in .env is rejected
    bad_env = tmp_path / "bad.env"
    bad_env.write_text("CORS_ALLOWED_ORIGINS=*\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Wildcard"):
        get_cors_origins_for_app(env_file=bad_env)


# ----------------------------------------------------------- MEDIUM-4 language
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Python döngüleri için alıştırma oluştur.", "tr"),
        ("C dilinde isaretci nedir ve nasil kullanilir?", "tr"),  # ASCII-folded Turkish!
        ("What is the difference between a process and a thread?", "en"),
        ("Create a short Python loop exercise.", "en"),
    ],
)
def test_medium4_language_detection_and_prompt_directive(
    question: str, expected: str
) -> None:
    assert detect_question_language(question) == expected
    chunk = RetrievedChunk(1, 1, "Not", "metin", 1, 1, 0.9, course_id=1)
    built = PromptBuilder().build(
        question=question, chunks=[chunk], mode=AnswerMode.EXERCISE
    )
    if expected == "tr":
        assert "Turkish (Türkçe)" in built.user_prompt
    else:
        assert "Write the entire 'answer' field in English." in built.user_prompt
