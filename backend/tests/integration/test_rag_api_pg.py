"""PostgreSQL API integration tests for materials, concurrent duplicates, and K64 real demo."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_token_service
from app.api.dependencies.rag import (
    get_embedding_provider,
    get_file_storage,
    get_llm_client,
)
from app.authorization.roles import Role
from app.core.security.passwords import Argon2PasswordHasher
from app.core.security.tokens import JwtTokenService
from app.database import get_db
from app.main import app
from app.models import EnrollmentStatus
from app.rag.embedding import OnnxE5EmbeddingProvider
from app.rag.generation import LLMRequest, LLMResponse, OllamaLLMClient
from app.repositories.course_enrollment_repository import (
    SqlAlchemyCourseEnrollmentRepository,
)
from app.repositories.course_repository import SqlAlchemyCourseRepository
from app.repositories.user_repository import SqlAlchemyUserRepository
from app.storage import LocalFileStorage
from tests.integration.rag_pg_helpers import TRUNCATE_ALL_SQL
from tests.rag.fakes import FakeEmbeddingProvider
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf

pytestmark = pytest.mark.postgres

_TEST_JWT_SECRET = "test-only-jwt-secret-key-at-least-32-bytes-long!"


@pytest.fixture()
def pg_api_env(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> Generator[dict, None, None]:
    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))

    token_service = JwtTokenService(secret_key=_TEST_JWT_SECRET)
    hasher = Argon2PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

    setup = pg_session_factory()
    try:
        users = SqlAlchemyUserRepository(setup)
        inst = users.create(
            email="inst@example.edu",
            hashed_password=hasher.hash("StrongPass123!"),
            first_name="Ali",
            last_name="Hoca",
            role=Role.INSTRUCTOR,
        )
        student = users.create(
            email="student@example.edu",
            hashed_password=hasher.hash("StrongPass123!"),
            first_name="Ayse",
            last_name="Ogrenci",
            role=Role.STUDENT,
        )
        courses = SqlAlchemyCourseRepository(setup)
        c1 = courses.create(code="CENG101", title="C Programming", instructor_id=inst.id)
        c2 = courses.create(code="CENG202", title="Other Course", instructor_id=inst.id)
        SqlAlchemyCourseEnrollmentRepository(setup).create(
            student_id=student.id, course_id=c1.id, status=EnrollmentStatus.ACTIVE
        )
    finally:
        setup.close()

    def _override_db():
        db = pg_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_file_storage] = lambda: LocalFileStorage(
        tmp_path / "uploads", max_bytes=10 * 1024 * 1024
    )
    try:
        yield {
            "client": TestClient(app),
            "c1_id": c1.id,
            "c2_id": c2.id,
            "inst_email": "inst@example.edu",
            "student_email": "student@example.edu",
            "password": "StrongPass123!",
        }
    finally:
        app.dependency_overrides.clear()
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_pg_concurrent_duplicate_upload_and_auth_regression(pg_api_env) -> None:
    class _OkLLM:
        model_name = "pg-fake-llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(True, "Pointer bellek adresi tutar [S1].", ("S1",), "pg-fake-llm")

    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddingProvider(
        dimension=8, max_tokens=64
    )
    app.dependency_overrides[get_llm_client] = lambda: _OkLLM()

    client: TestClient = pg_api_env["client"]
    c1 = pg_api_env["c1_id"]
    inst_h = _login(client, pg_api_env["inst_email"], pg_api_env["password"])

    # Concurrent duplicate JSON uploads -> exactly 1 succeeds (201), 1 conflicts (409)
    def post_same() -> int:
        with TestClient(app) as local_client:
            r = local_client.post(
                f"/api/v1/courses/{c1}/materials",
                headers=inst_h,
                json={"title": "Dup Test", "text": "Ayni icerik eşzamanlı yükleme testi."},
            )
            return r.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted([f.result() for f in [pool.submit(post_same), pool.submit(post_same)]])
    assert codes == [201, 409]

    # Existing health endpoint still works
    assert client.get("/api/v1/health").status_code == 200


def test_high2_pg_pool_releases_connection_during_embedding_and_llm(
    migrated_pg_engine: Engine,
    pg_api_env,
) -> None:
    """Verify real SQLAlchemy QueuePool has 0 checked-out connections during
    long-running embedding and LLM calls (HIGH-2 remediation proof).
    """
    observed: dict[str, int] = {}

    class _PoolCheckingEmbedding(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            observed["during_embed_documents"] = migrated_pg_engine.pool.checkedout()
            return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

        def embed_query(self, text: str):
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    class _PoolCheckingLLM:
        model_name = "pool-check-llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            observed["during_llm_generate"] = migrated_pg_engine.pool.checkedout()
            return LLMResponse(
                True, "Pointer bellek adresi saklar [S1].", ("S1",), "pool-check-llm"
            )

    emb = _PoolCheckingEmbedding(dimension=8, max_tokens=64)
    app.dependency_overrides[get_embedding_provider] = lambda: emb
    app.dependency_overrides[get_llm_client] = lambda: _PoolCheckingLLM()

    client: TestClient = pg_api_env["client"]
    c1 = pg_api_env["c1_id"]
    inst_h = _login(client, pg_api_env["inst_email"], pg_api_env["password"])
    stu_h = _login(client, pg_api_env["student_email"], pg_api_env["password"])

    up = client.post(
        f"/api/v1/courses/{c1}/materials",
        headers=inst_h,
        json={"title": "Pool Test", "text": "C dilinde pointer bellek adresi saklar.", "page": 4},
    )
    assert up.status_code == 201
    assert up.json()["processing_status"] == "processed"
    assert up.json()["page"] == 4
    assert observed["during_embed_documents"] == 0

    ask = client.post(
        f"/api/v1/courses/{c1}/assistant",
        headers=stu_h,
        json={"question": "C dilinde pointer bellek adresi saklar."},
    )
    assert ask.status_code == 200
    assert observed["during_llm_generate"] == 0
    assert migrated_pg_engine.pool.checkedout() == 0


@pytest.mark.real_model
def test_k64_real_api_demo_with_e5_qwen3_and_postgres(pg_api_env) -> None:
    """Full K64 real demo: login -> PDF upload -> E5 retrieval -> Qwen3 answer -> 404 isolation."""
    if os.environ.get("STUDYGRAPH_RUN_REAL_API_DEMO") != "1":
        pytest.skip("Set STUDYGRAPH_RUN_REAL_API_DEMO=1 to run the real K64 API demo.")

    repo_root = Path(__file__).resolve().parents[3]
    e5 = OnnxE5EmbeddingProvider(repo_root / "models" / "multilingual-e5-small")
    ollama = OllamaLLMClient(
        base_url="http://127.0.0.1:11434",
        model_name="qwen3:4b",
        timeout_seconds=90.0,
    )
    app.dependency_overrides[get_embedding_provider] = lambda: e5
    app.dependency_overrides[get_llm_client] = lambda: ollama

    client: TestClient = pg_api_env["client"]
    c1, c2 = pg_api_env["c1_id"], pg_api_env["c2_id"]

    # 1. Instructor login & multipart PDF upload
    inst_h = _login(client, pg_api_env["inst_email"], pg_api_env["password"])
    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("1. C Dilinde İşaretçiler", x=72, y=730, size=15, font="bold"),
                    TextItem("C dilinde işaretçi (pointer) başka bir değişkenin bellek adresini saklar.", x=72, y=700),
                    TextItem("int x = 42;", x=72, y=670, size=10, font="code"),
                    TextItem("int *p = &x;", x=72, y=656, size=10, font="code"),
                    TextItem('printf("%d\\n", *p);', x=72, y=642, size=10, font="code"),
                )
            )
        ]
    )
    t_up = time.perf_counter()
    up = client.post(
        f"/api/v1/courses/{c1}/materials/upload",
        headers=inst_h,
        files={"file": ("c_pointers.pdf", pdf_bytes, "application/pdf")},
        data={"title": "C Pointers Ders Notu"},
    )
    up_s = time.perf_counter() - t_up
    assert up.status_code == 201
    assert up.json()["processing_status"] == "processed"

    # 2. Student login & ask question (real E5 + real Qwen3)
    stu_h = _login(client, pg_api_env["student_email"], pg_api_env["password"])
    t_ask = time.perf_counter()
    ask = client.post(
        f"/api/v1/courses/{c1}/assistant",
        headers=stu_h,
        json={"question": "C dilinde işaretçi nedir ve & operatörü ne işe yarar?", "mode": "topic_explanation"},
    )
    ask_s = time.perf_counter() - t_ask
    assert ask.status_code == 200
    data = ask.json()
    print(f"\n[K64_DEMO] upload_s={up_s:.2f} ask_s={ask_s:.2f} grounded={data['grounded']} model={data['model_name']}")
    print("[K64_SOURCES]", data["sources"])
    print("[K64_ANSWER]", data["answer"])
    assert data["grounded"] is True
    assert data["fallback_used"] is False
    assert data["sources"][0]["title"] == "C Pointers Ders Notu"
    assert data["sources"][0]["page"] == 1

    # 3. Student accessing unenrolled course c2 -> 404
    denied = client.post(
        f"/api/v1/courses/{c2}/assistant",
        headers=stu_h,
        json={"question": "Pointer nedir?"},
    )
    assert denied.status_code == 404
