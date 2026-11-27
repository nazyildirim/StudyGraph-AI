"""Comprehensive unit/API tests for materials and assistant endpoints (K63).

Runs completely stateless with in-memory fakes (no PostgreSQL, ONNX, or Ollama).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.dependencies.auth import get_current_user
from app.database import get_db
from app.api.dependencies.rag import (
    get_material_service,
    get_rag_assistant_service,
)
from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.roles import Role
from app.core.config import Settings, get_settings
from app.main import app
from app.rag.chunking import StructureAwareChunker
from app.rag.domain import (
    ChunkDraft,
    ProcessingStatus,
    RetrievalMethod,
    RetrievedChunk,
)
from app.rag.generation import (
    CitationValidator,
    ExtractiveLLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    PromptBuilder,
)
from app.rag.parsing import PdfDocumentParser, PlainTextParser
from app.rag.retrieval import CourseRetrievalService, SemanticRetriever
from app.repositories.errors import (
    MaterialAlreadyExistsError,
    MaterialAlreadyProcessedError,
    MaterialAlreadyProcessingError,
    MaterialNotFoundError,
)
from app.services.material_ingestion_service import MaterialIngestionService
from app.services.material_service import MaterialService
from app.services.rag_assistant_service import RagAssistantService
from app.storage import LocalFileStorage
from tests.rag.fakes import FakeEmbeddingProvider
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf


def _user(user_id: int, role: Role, *, is_active: bool = True):
    return SimpleNamespace(id=user_id, role=role.value, is_active=is_active)


@dataclass
class _MemCourseRepo:
    courses: dict[int, object]

    def get_by_id(self, course_id: int):
        return self.courses.get(course_id)


@dataclass
class _MemEnrollmentRepo:
    active: set[tuple[int, int]]

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool:
        return (student_id, course_id) in self.active


@dataclass
class _MemMaterial:
    id: int
    course_id: int
    uploaded_by: int | None
    title: str
    file_path: str
    file_type: str
    file_size_bytes: int | None
    content_hash: str
    unverified_outcome_ref: str | None = None
    processing_status: str = ProcessingStatus.PENDING.value
    error_message: str | None = None
    extraction_report: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class _MemMaterialRepo:
    rows: dict[int, _MemMaterial] = field(default_factory=dict)
    next_id: int = 1

    def get_by_id(self, material_id: int):
        return self.rows.get(material_id)

    def list_by_course(self, course_id: int):
        return [m for m in self.rows.values() if m.course_id == course_id]

    def create(self, **kwargs):
        for existing in self.rows.values():
            if (
                existing.course_id == kwargs["course_id"]
                and existing.content_hash == kwargs["content_hash"]
            ):
                raise MaterialAlreadyExistsError(kwargs["content_hash"])
        mat = _MemMaterial(id=self.next_id, **kwargs)
        self.rows[self.next_id] = mat
        self.next_id += 1
        return mat

    def claim_for_processing(self, material_id: int):
        mat = self.rows.get(material_id)
        if mat is None:
            raise MaterialNotFoundError(str(material_id))
        if mat.processing_status == ProcessingStatus.PROCESSING.value:
            raise MaterialAlreadyProcessingError(str(material_id))
        if mat.processing_status == ProcessingStatus.PROCESSED.value:
            raise MaterialAlreadyProcessedError(str(material_id))
        mat.processing_status = ProcessingStatus.PROCESSING.value
        return mat

    def update_processing_status(self, material_id: int, status: ProcessingStatus, *, error_message=None, extraction_report=None):
        mat = self.rows[material_id]
        mat.processing_status = status.value
        mat.error_message = error_message if status is ProcessingStatus.FAILED else None
        if extraction_report is not None:
            mat.extraction_report = extraction_report
        return mat

    def delete(self, material_id: int) -> bool:
        return self.rows.pop(material_id, None) is not None


@dataclass
class _MemChunkRepo:
    materials: _MemMaterialRepo
    chunks: dict[int, list[tuple[int, ChunkDraft, bytes]]] = field(default_factory=dict)
    next_id: int = 1

    def save_embedded_chunks_and_mark_processed(
        self,
        *,
        material_id: int,
        drafts: list[ChunkDraft],
        embeddings: list[bytes],
        embedding_model: str,
        embedding_dim: int,
        extraction_report: str | None = None,
    ):
        stored = []
        for d, e in zip(drafts, embeddings, strict=True):
            stored.append((self.next_id, d, e))
            self.next_id += 1
        self.chunks[material_id] = stored
        self.materials.update_processing_status(
            material_id, ProcessingStatus.PROCESSED, extraction_report=extraction_report
        )
        return stored


class _MemVectorStore:
    def __init__(self, mat_repo: _MemMaterialRepo, chunk_repo: _MemChunkRepo) -> None:
        self._mats = mat_repo
        self._chunks = chunk_repo

    def search(self, *, course_id: int, query_vector, expected_model: str, expected_dim: int, top_k: int = 5):
        import numpy as np

        hits = []
        for mat in self._mats.list_by_course(course_id):
            if mat.processing_status != ProcessingStatus.PROCESSED.value:
                continue
            for cid, draft, raw in self._chunks.chunks.get(mat.id, []):
                vec = np.frombuffer(raw, dtype="<f4")
                q = np.asarray(query_vector, dtype="<f4")
                score = float(np.dot(vec, q))
                # Return high score for same-course match unless query says "unrelated"
                hits.append(
                    RetrievedChunk(
                        chunk_id=cid,
                        material_id=mat.id,
                        material_title=mat.title,
                        content=draft.content,
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        score=score,
                        course_id=course_id,
                        retrieval_method=RetrievalMethod.SEMANTIC_E5.value,
                    )
                )
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:top_k]


@dataclass
class _MemQueryRepo:
    rows: list[dict] = field(default_factory=list)

    def create_with_citations(self, **kwargs):
        kwargs["id"] = len(self.rows) + 1
        self.rows.append(kwargs)
        return SimpleNamespace(id=kwargs["id"])


class _StubLLM:
    model_name = "stub-llm"

    def __init__(self, *, raise_timeout: bool = False) -> None:
        self._raise_timeout = raise_timeout

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self._raise_timeout:
            raise LLMTimeoutError("timeout")
        sid = request.sources[0].source_id
        return LLMResponse(
            sufficient_context=True,
            answer=f"Grounded answer ({request.mode.value}) [{sid}].",
            cited_source_ids=(sid,),
            model_name=self.model_name,
        )


@pytest.fixture()
def rag_env(tmp_path: Path):
    courses = _MemCourseRepo(
        {
            1: SimpleNamespace(id=1, instructor_id=10, is_active=True),
            2: SimpleNamespace(id=2, instructor_id=20, is_active=True),
        }
    )
    enrollments = _MemEnrollmentRepo({(100, 1)})
    policy = CourseAccessPolicy(
        course_repository=courses,  # type: ignore[arg-type]
        enrollment_repository=enrollments,  # type: ignore[arg-type]
    )
    mat_repo = _MemMaterialRepo()
    chunk_repo = _MemChunkRepo(mat_repo)
    storage = LocalFileStorage(tmp_path / "uploads", max_bytes=8192)
    emb = FakeEmbeddingProvider(dimension=8, max_tokens=64)
    ingestion = MaterialIngestionService(
        material_repository=mat_repo,  # type: ignore[arg-type]
        chunk_repository=chunk_repo,  # type: ignore[arg-type]
        parsers={
            "application/pdf": PdfDocumentParser(),
            "text/plain": PlainTextParser(),
        },
        chunker=StructureAwareChunker(chunk_size=300, chunk_overlap=20),
        embedding_provider=emb,
    )
    mat_service = MaterialService(
        access_policy=policy,
        material_repository=mat_repo,  # type: ignore[arg-type]
        file_storage=storage,
        ingestion_service=ingestion,
    )
    query_repo = _MemQueryRepo()
    llm_holder = {"client": _StubLLM()}

    def build_assistant(min_score: float = -1.0):
        retrieval = CourseRetrievalService(
            access_policy=policy,
            primary_retriever=SemanticRetriever(
                embedding_provider=emb,
                vector_store=_MemVectorStore(mat_repo, chunk_repo),  # type: ignore[arg-type]
            ),
            primary_min_score=min_score,
        )
        return RagAssistantService(
            access_policy=policy,
            retrieval_service=retrieval,
            prompt_builder=PromptBuilder(),
            llm_client=llm_holder["client"],  # type: ignore[arg-type]
            citation_validator=CitationValidator(),
            query_repository=query_repo,  # type: ignore[arg-type]
            extractive_fallback=ExtractiveLLMClient(),
        )

    active_user = {"user": _user(10, Role.INSTRUCTOR)}
    min_score_holder = {"val": -1.0}

    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    app.dependency_overrides[get_material_service] = lambda: mat_service
    app.dependency_overrides[get_rag_assistant_service] = lambda: build_assistant(
        min_score_holder["val"]
    )
    try:
        yield {
            "client": TestClient(app),
            "set_user": lambda u: active_user.__setitem__("user", u),
            "set_llm": lambda c: llm_holder.__setitem__("client", c),
            "set_min_score": lambda v: min_score_holder.__setitem__("val", v),
            "upload_dir": tmp_path / "uploads",
            "mat_repo": mat_repo,
        }
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------- Auth & CORS & Settings
def test_unauthenticated_and_invalid_jwt_rejected_with_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _dummy_db():
        yield None

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = _dummy_db
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "test-only-synthetic-jwt-secret-key-at-least-32-bytes",
    )
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        assert client.get("/api/v1/courses/1/materials").status_code == 401
        assert (
            client.post("/api/v1/courses/1/assistant", json={"question": "hi"}).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/courses/1/materials",
                headers={"Authorization": "Bearer invalid.jwt.token"},
            ).status_code
            == 401
        )
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()
        get_settings.cache_clear()


def test_cors_preflight_allows_configured_origin_and_blocks_unknown() -> None:
    client = TestClient(app)
    ok = client.options(
        "/api/v1/courses/1/materials",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert ok.status_code == 200
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"

    blocked = client.options(
        "/api/v1/courses/1/materials",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in blocked.headers

    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_allowed_origins="*")


# --------------------------------------- Materials CRUD, RBAC, Upload Safety
def test_materials_canonical_and_compat_flows_and_rbac(rag_env) -> None:
    client: TestClient = rag_env["client"]
    set_user = rag_env["set_user"]

    # 1. Owning instructor creates JSON text material (canonical -> 201 single record)
    set_user(_user(10, Role.INSTRUCTOR))
    r1 = client.post(
        "/api/v1/courses/1/materials",
        json={"title": "Hafta 1", "text": "C dilinde pointer bellek adresi tutar.", "outcomeId": "k1"},
    )
    assert r1.status_code == 201
    body = r1.json()
    assert body["title"] == "Hafta 1"
    assert body["processing_status"] == "processed"
    assert body["outcomeId"] == "k1"
    assert "file_path" not in body  # never leak local paths
    m1_id = body["id"]

    # Duplicate content -> 409 Conflict
    dup = client.post(
        "/api/v1/courses/1/materials",
        json={"title": "Hafta 1 Kopya", "text": "C dilinde pointer bellek adresi tutar."},
    )
    assert dup.status_code == 409

    # 2. Multipart PDF upload & TXT upload
    pdf_bytes = build_pdf([PageSpec(items=(TextItem("PDF icerigi pointer ornegi.", x=72, y=700),))])
    r_pdf = client.post(
        "/api/v1/courses/1/materials/upload",
        files={"file": ("pointers.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Pointers PDF"},
    )
    assert r_pdf.status_code == 201
    assert r_pdf.json()["file_type"] == "application/pdf"
    assert r_pdf.json()["page_count"] == 1

    r_txt = client.post(
        "/api/v1/courses/1/materials/upload",
        files={"file": ("notes.txt", "Python döngü notları.".encode("utf-8"), "text/plain")},
    )
    assert r_txt.status_code == 201
    assert r_txt.json()["file_type"] == "text/plain"

    # 3. Upload security: 413 oversized, 415 bad MIME/signature, 422 path traversal
    assert (
        client.post(
            "/api/v1/courses/1/materials/upload",
            files={"file": ("big.txt", b"a" * 9000, "text/plain")},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/v1/courses/1/materials/upload",
            files={"file": ("fake.pdf", b"not a real pdf", "application/pdf")},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/courses/1/materials/upload",
            files={"file": ("../etc/passwd.txt", b"hello", "text/plain")},
        ).status_code
        == 422
    )

    # 4. Student can list/get enrolled course, CANNOT upload or delete (403)
    set_user(_user(100, Role.STUDENT))
    assert len(client.get("/api/v1/courses/1/materials").json()) == 3
    assert client.get(f"/api/v1/courses/1/materials/{m1_id}").status_code == 200
    assert (
        client.post(
            "/api/v1/courses/1/materials", json={"title": "x", "text": "y"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/courses/1/materials/{m1_id}").status_code == 403

    # 5. Another instructor cannot access or upload to course 1 (404)
    set_user(_user(20, Role.INSTRUCTOR))
    assert client.get("/api/v1/courses/1/materials").status_code == 404
    assert (
        client.post(
            "/api/v1/courses/1/materials", json={"title": "x", "text": "y"}
        ).status_code
        == 404
    )

    # 6. Cross-course material_id rejected (404)
    set_user(_user(10, Role.INSTRUCTOR))
    assert client.get(f"/api/v1/courses/2/materials/{m1_id}").status_code == 404
    assert client.delete(f"/api/v1/courses/2/materials/{m1_id}").status_code == 404

    # 7. Admin can manage materials + canonical DELETE returns 204
    set_user(_user(999, Role.ADMIN))
    assert client.delete(f"/api/v1/courses/1/materials/{m1_id}").status_code == 204

    # 8. Unprefixed frontend compat endpoints return updated list array on POST & DELETE
    set_user(_user(10, Role.INSTRUCTOR))
    c_post = client.post(
        "/courses/1/materials",
        json={"title": "Compat Not", "text": "Frontend uyumlu metin.", "page": 1, "outcome_id": "k2"},
    )
    assert c_post.status_code == 201 and isinstance(c_post.json(), list)
    new_id = [m["id"] for m in c_post.json() if m["title"] == "Compat Not"][0]

    c_del = client.delete(f"/courses/1/materials/{new_id}")
    assert c_del.status_code == 200 and isinstance(c_del.json(), list)
    assert all(m["id"] != new_id for m in c_del.json())


def test_failed_ingestion_cleans_up_uploaded_file(rag_env) -> None:
    client: TestClient = rag_env["client"]
    rag_env["set_user"](_user(10, Role.INSTRUCTOR))
    upload_dir: Path = rag_env["upload_dir"]

    # Truncated PDF passes %PDF- magic check, fails parser -> marked failed & file removed
    resp = client.post(
        "/api/v1/courses/1/materials/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4\ntruncated", "application/pdf")},
    )
    assert resp.status_code == 201
    assert resp.json()["processing_status"] == "failed"
    assert list(upload_dir.glob("*")) == []  # zero orphan files left behind

    # MEDIUM-1 contract: re-uploading identical content_hash while failed row exists -> 409
    dup_failed = client.post(
        "/api/v1/courses/1/materials/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4\ntruncated", "application/pdf")},
    )
    assert dup_failed.status_code == 409


def test_low3_json_material_preserves_user_reported_page_in_citations(rag_env) -> None:
    client: TestClient = rag_env["client"]
    set_user = rag_env["set_user"]

    # Invalid page=0 rejected (422)
    set_user(_user(10, Role.INSTRUCTOR))
    bad = client.post(
        "/api/v1/courses/1/materials",
        json={"title": "Bad Page", "text": "Metin", "page": 0},
    )
    assert bad.status_code == 422

    # Valid user-reported page=7 preserved in MaterialResponse and Assistant sources
    ok = client.post(
        "/api/v1/courses/1/materials",
        json={"title": "Hafta 4 Notu", "text": "C dilinde malloc dinamik bellek ayirir.", "page": 7},
    )
    assert ok.status_code == 201
    assert ok.json()["page"] == 7

    set_user(_user(100, Role.STUDENT))
    ans = client.post(
        "/api/v1/courses/1/assistant",
        json={"question": "malloc nedir?"},
    )
    assert ans.status_code == 200
    assert ans.json()["sources"][0]["page"] == 7
    assert ans.json()["sources"][0]["page_start"] == 7


# ------------------------------------------------------------- Assistant API
def test_assistant_modes_auth_no_sources_and_fallback(rag_env) -> None:
    client: TestClient = rag_env["client"]
    set_user = rag_env["set_user"]

    # Seed one material as instructor
    set_user(_user(10, Role.INSTRUCTOR))
    client.post(
        "/api/v1/courses/1/materials",
        json={"title": "C Pointers", "text": "C dilinde pointer bellek adresini saklar."},
    )

    # Enrolled student asks in all 3 modes (canonical + compat)
    set_user(_user(100, Role.STUDENT))
    for mode in ("topic_explanation", "code_example", "exercise"):
        res = client.post(
            "/api/v1/courses/1/assistant",
            json={"question": "Pointer nedir?", "mode": mode, "outcome_id": "k1"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["grounded"] is True
        assert data["answer_mode"] == mode
        assert data["sources"][0]["title"] == "C Pointers"
        assert data["sources"][0]["material_id"] == 1

    # Compat route with only {question, outcome_id} defaults to topic_explanation
    compat = client.post(
        "/courses/1/assistant",
        json={"question": "Pointer nedir?", "outcome_id": "k1"},
    )
    assert compat.status_code == 200
    assert compat.json()["answer_mode"] == "topic_explanation"

    # Unenrolled student -> 404
    set_user(_user(101, Role.STUDENT))
    assert (
        client.post(
            "/api/v1/courses/1/assistant", json={"question": "Pointer nedir?"}
        ).status_code
        == 404
    )

    # Inactive user -> 404
    set_user(_user(100, Role.STUDENT, is_active=False))
    assert (
        client.post(
            "/api/v1/courses/1/assistant", json={"question": "Pointer nedir?"}
        ).status_code
        == 404
    )

    # No sources above threshold -> grounded=False, sources=[]
    set_user(_user(100, Role.STUDENT))
    rag_env["set_min_score"](0.9999)
    no_src = client.post(
        "/api/v1/courses/1/assistant", json={"question": "Alakasiz soru"}
    )
    assert no_src.status_code == 200
    assert no_src.json()["grounded"] is False
    assert no_src.json()["sources"] == []

    # Timeout -> extractive fallback explicitly flagged
    rag_env["set_min_score"](-1.0)
    rag_env["set_llm"](_StubLLM(raise_timeout=True))
    fb = client.post(
        "/api/v1/courses/1/assistant", json={"question": "Pointer nedir?"}
    )
    assert fb.status_code == 200
    assert fb.json()["fallback_used"] is True
    assert fb.json()["model_name"] == "extractive-fallback"
