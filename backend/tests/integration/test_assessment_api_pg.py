"""Real PostgreSQL + JWT + real LearningAnalysisService E2E API test (Phase 8)."""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security.passwords import Argon2PasswordHasher
from app.database import get_db
from app.main import app
from app.repositories import SqlAlchemyLearningOutcomeRepository
from tests.integration.rag_pg_helpers import insert_course

pytestmark = pytest.mark.postgres

TRUNCATE_ALL_SQL = (
    "TRUNCATE TABLE study_recommendations, mastery_records, student_responses, "
    "student_assessments, assessment_questions, assessments, question_options, "
    "questions, prerequisites, learning_outcomes, rag_query_citations, rag_queries, "
    "material_chunks, course_materials, course_enrollments, courses, users "
    "RESTART IDENTITY CASCADE"
)


def _insert_real_user(
    conn,
    *,
    email: str,
    password: str,
    role: str,
    is_active: bool = True,
) -> int:
    hashed = Argon2PasswordHasher(
        time_cost=2, memory_cost=19456, parallelism=1
    ).hash(password)
    return conn.execute(
        text(
            "INSERT INTO users (email, hashed_password, first_name, last_name, role, is_active) "
            "VALUES (:email, :pw, 'Test', 'User', :role, :active) RETURNING id"
        ),
        {"email": email, "pw": hashed, "role": role, "active": is_active},
    ).scalar_one()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def pg_api_client(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, Engine, sessionmaker[Session]], None, None]:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-issue7-e2e-at-least-32b")
    get_settings.cache_clear()

    with migrated_pg_engine.begin() as conn:
        conn.execute(text(TRUNCATE_ALL_SQL))

    def _override_get_db() -> Generator[Session, None, None]:
        with pg_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app), migrated_pg_engine, pg_session_factory
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        with migrated_pg_engine.begin() as conn:
            conn.execute(text(TRUNCATE_ALL_SQL))


def test_full_real_e2e_jwt_question_bank_initial_exam_mastery_and_retest(
    pg_api_client: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, engine, session_factory = pg_api_client

    # Seed real users, course, enrollment, and DAG outcomes (LO1 -> LO2 -> LO3, LO4 unassessed)
    with engine.begin() as conn:
        inst_id = _insert_real_user(
            conn, email="inst@edu.tr", password="Password123!", role="instructor"
        )
        other_inst_id = _insert_real_user(
            conn, email="other@edu.tr", password="Password123!", role="instructor"
        )
        stu_id = _insert_real_user(
            conn, email="stu@edu.tr", password="Password123!", role="student"
        )
        stu2_id = _insert_real_user(
            conn, email="stu2@edu.tr", password="Password123!", role="student"
        )
        c1_id = insert_course(conn, "CENG101", inst_id)
        conn.execute(
            text(
                "INSERT INTO course_enrollments (student_id, course_id) "
                "VALUES (:s1, :c), (:s2, :c)"
            ),
            {"s1": stu_id, "s2": stu2_id, "c": c1_id},
        )

    with session_factory() as session:
        with session.begin():
            lo_repo = SqlAlchemyLearningOutcomeRepository(session)
            lo1 = lo_repo.create_outcome(course_id=c1_id, code="LO-1", title="Basics", order_index=1)
            lo2 = lo_repo.create_outcome(course_id=c1_id, code="LO-2", title="Loops", order_index=2)
            lo3 = lo_repo.create_outcome(course_id=c1_id, code="LO-3", title="Sorting", order_index=3)
            lo4 = lo_repo.create_outcome(course_id=c1_id, code="LO-4", title="Trees", order_index=4)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo1.id, dependent_outcome_id=lo2.id)
            lo_repo.add_prerequisite(course_id=c1_id, prerequisite_outcome_id=lo2.id, dependent_outcome_id=lo3.id)
            lo1_id, lo2_id, lo3_id, lo4_id = lo1.id, lo2.id, lo3.id, lo4.id

    # 1. Real JWT logins
    inst_headers = _login(client, "inst@edu.tr", "Password123!")
    other_inst_headers = _login(client, "other@edu.tr", "Password123!")
    stu_headers = _login(client, "stu@edu.tr", "Password123!")
    stu2_headers = _login(client, "stu2@edu.tr", "Password123!")

    # 2. Instructor creates questions; student gets 403; non-owning instructor gets 404
    correct_opt_by_qid: dict[int, int] = {}
    wrong_opt_by_qid: dict[int, int] = {}
    for oid, count in ((lo1_id, 2), (lo2_id, 7), (lo3_id, 2)):
        for idx in range(count):
            resp = client.post(
                f"/api/v1/courses/{c1_id}/questions",
                headers=inst_headers,
                json={
                    "learning_outcome_id": oid,
                    "question_text": f"LO{oid} Q{idx + 1}",
                    "difficulty_level": "medium",
                    "points": 1.0,
                    "options": [
                        {"option_text": f"Opt {o}", "is_correct": o == 0, "order_index": o}
                        for o in range(4)
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            correct_opt_by_qid[body["id"]] = body["options"][0]["id"]
            wrong_opt_by_qid[body["id"]] = body["options"][1]["id"]

    assert (
        client.get(f"/api/v1/courses/{c1_id}/questions", headers=stu_headers).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/courses/{c1_id}/questions", headers=other_inst_headers
        ).status_code
        == 404
    )

    # 3. Student lists outcomes & starts 6-question diagnostic exam (201 -> 200 resume)
    r_outcomes = client.get(f"/api/v1/courses/{c1_id}/outcomes", headers=stu_headers)
    assert r_outcomes.status_code == 200
    assert len(r_outcomes.json()) == 4

    r_diag = client.post(
        f"/api/v1/courses/{c1_id}/exams/initial",
        headers=stu_headers,
        json={"question_count": 6},
    )
    assert r_diag.status_code == 201, r_diag.text
    diag_body = r_diag.json()
    attempt_id = diag_body["attempt_id"]
    assert "is_correct" not in r_diag.text

    r_diag_resume = client.post(
        f"/api/v1/courses/{c1_id}/exams/initial",
        headers=stu_headers,
        json={"question_count": 6},
    )
    assert r_diag_resume.status_code == 200
    assert r_diag_resume.json()["attempt_id"] == attempt_id

    # Other student cannot view this attempt (404); incomplete result returns 409
    assert (
        client.get(
            f"/api/v1/courses/{c1_id}/exams/attempts/{attempt_id}",
            headers=stu2_headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/courses/{c1_id}/exams/attempts/{attempt_id}/result",
            headers=stu_headers,
        ).status_code
        == 409
    )

    # 4. Student submits diagnostic: LO1=100%, LO2=0%, LO3=0% (blocked by LO2), LO4=unassessed
    diag_qids = {q["question_id"] for q in diag_body["questions"]}
    submit_payload = {
        "answers": [
            {
                "question_id": q["question_id"],
                "selected_option_id": (
                    correct_opt_by_qid[q["question_id"]]
                    if q["learning_outcome_id"] == lo1_id
                    else wrong_opt_by_qid[q["question_id"]]
                ),
            }
            for q in diag_body["questions"]
        ]
    }
    r_sub = client.post(
        f"/api/v1/courses/{c1_id}/exams/attempts/{attempt_id}/submit",
        headers=stu_headers,
        json=submit_payload,
    )
    assert r_sub.status_code == 200, r_sub.text
    assert r_sub.json()["mastery_summary"] is not None

    # Double submit -> 409 Conflict
    assert (
        client.post(
            f"/api/v1/courses/{c1_id}/exams/attempts/{attempt_id}/submit",
            headers=stu_headers,
            json=submit_payload,
        ).status_code
        == 409
    )

    # 5. Check real mastery map & recommendations (zero mocks!)
    r_mastery = client.get(f"/api/v1/courses/{c1_id}/mastery", headers=stu_headers)
    assert r_mastery.status_code == 200
    m_by_oid = {o["learning_outcome_id"]: o for o in r_mastery.json()["outcomes"]}
    assert m_by_oid[lo1_id]["mastery_score"] == 100.0
    assert m_by_oid[lo2_id]["mastery_score"] == 0.0
    assert m_by_oid[lo4_id]["is_assessed"] is False
    assert m_by_oid[lo4_id]["mastery_score"] is None

    r_recs = client.get(
        f"/api/v1/courses/{c1_id}/recommendations", headers=stu_headers
    )
    assert r_recs.status_code == 200
    recs_by_oid = {
        r["learning_outcome_id"]: r for r in r_recs.json()["recommendations"]
    }
    assert recs_by_oid[lo1_id]["status"] == "completed"
    assert recs_by_oid[lo2_id]["status"] == "review"
    assert recs_by_oid[lo3_id]["status"] == "blocked"
    assert recs_by_oid[lo3_id]["missing_prerequisites"] == [lo2_id]
    assert recs_by_oid[lo4_id]["status"] == "study"

    # 6. Student starts general retest (5 UNSEEN questions from LO2) -> submits all correct
    r_retest = client.post(
        f"/api/v1/courses/{c1_id}/exams/retest", headers=stu_headers
    )
    assert r_retest.status_code == 201, r_retest.text
    retest_body = r_retest.json()
    assert retest_body["actual_count"] == 5
    assert retest_body["unseen_question_count"] == 5
    assert retest_body["reused_question_count"] == 0
    retest_qids = [q["question_id"] for q in retest_body["questions"]]
    assert not (set(retest_qids) & diag_qids)

    # Incompatible retest target while in_progress -> 409 Conflict
    assert (
        client.post(
            f"/api/v1/courses/{c1_id}/exams/retest",
            headers=stu_headers,
            json={"difficulty": "hard"},
        ).status_code
        == 409
    )

    r_retest_sub = client.post(
        f"/api/v1/courses/{c1_id}/exams/attempts/{retest_body['attempt_id']}/submit",
        headers=stu_headers,
        json={
            "answers": [
                {"question_id": qid, "selected_option_id": correct_opt_by_qid[qid]}
                for qid in retest_qids
            ]
        },
    )
    assert r_retest_sub.status_code == 200, r_retest_sub.text

    # 7. Verify updated mastery map & unblocked LO3!
    r_mastery2 = client.get(f"/api/v1/courses/{c1_id}/mastery", headers=stu_headers)
    m2 = {o["learning_outcome_id"]: o for o in r_mastery2.json()["outcomes"]}
    assert m2[lo1_id]["total_attempts"] == 1
    assert m2[lo2_id]["mastery_score"] == 100.0 and m2[lo2_id]["total_attempts"] == 2
    assert m2[lo3_id]["mastery_score"] == 0.0 and m2[lo3_id]["total_attempts"] == 1
    assert m2[lo4_id]["is_assessed"] is False and m2[lo4_id]["mastery_score"] is None

    r_recs2 = client.get(
        f"/api/v1/courses/{c1_id}/recommendations", headers=stu_headers
    )
    recs2 = {r["learning_outcome_id"]: r for r in r_recs2.json()["recommendations"]}
    assert recs2[lo2_id]["status"] == "completed"
    assert recs2[lo3_id]["status"] == "review"
    assert recs2[lo3_id]["missing_prerequisites"] == []

    # 8. History returns both completed attempts for stu1 and empty for stu2
    r_hist = client.get(f"/api/v1/courses/{c1_id}/exams/history", headers=stu_headers)
    assert r_hist.status_code == 200 and len(r_hist.json()) == 2
    assert (
        client.get(
            f"/api/v1/courses/{c1_id}/exams/history", headers=stu2_headers
        ).json()
        == []
    )
