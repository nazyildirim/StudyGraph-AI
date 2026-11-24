
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_sample_payload():
    """API testleri icin ornek sinav verisi."""

    return {
        "course_id": "PYTHON",
        "outcomes": [
            {
                "id": "A",
                "course_id": "PYTHON",
                "title": "Python Temelleri",
            },
            {
                "id": "B",
                "course_id": "PYTHON",
                "title": "Degiskenler",
            },
            {
                "id": "C",
                "course_id": "PYTHON",
                "title": "Donguler",
            },
        ],
        "prerequisite_edges": [
            {
                "outcome_id": "B",
                "prerequisite_id": "A",
            },
            {
                "outcome_id": "C",
                "prerequisite_id": "B",
            },
        ],
        "question_results": [
            {
                "question_id": "Q1",
                "outcome_id": "A",
                "is_correct": True,
            },
            {
                "question_id": "Q2",
                "outcome_id": "B",
                "is_correct": False,
            },
            {
                "question_id": "Q3",
                "outcome_id": "C",
                "is_correct": False,
            },
        ],
        "mastery_threshold": 70.0,
    }


def test_successful_learning_analysis_api():
    """API dogru analiz ve onerileri dondurmeli."""

    response = client.post(
        "/api/v1/learning-analyses",
        json=create_sample_payload(),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["course_id"] == "PYTHON"
    assert data["learning_order"] == ["A", "B", "C"]

    scores = {
        item["outcome_id"]: item["score_percent"]
        for item in data["scores"]
    }

    assert scores == {
        "A": 100.0,
        "B": 0.0,
        "C": 0.0,
    }

    statuses = [
        item["status"]
        for item in data["recommendations"]
    ]

    assert statuses == [
        "completed",
        "review",
        "blocked",
    ]

    assert (
        data["recommendations"][2]["missing_prerequisites"]
        == ["B"]
    )


def test_retest_updates_api_recommendations():
    """Yeni sinav sonuclari yeni oneriler olusturmali."""

    initial_payload = create_sample_payload()

    initial_payload["question_results"][0]["is_correct"] = False

    initial_response = client.post(
        "/api/v1/learning-analyses",
        json=initial_payload,
    )

    assert initial_response.status_code == 200

    initial_statuses = [
        item["status"]
        for item in initial_response.json()["recommendations"]
    ]

    assert initial_statuses == [
        "review",
        "blocked",
        "blocked",
    ]

    updated_payload = create_sample_payload()

    updated_payload["question_results"][1]["is_correct"] = True

    updated_response = client.post(
        "/api/v1/learning-analyses",
        json=updated_payload,
    )

    assert updated_response.status_code == 200

    updated_statuses = [
        item["status"]
        for item in updated_response.json()["recommendations"]
    ]

    assert updated_statuses == [
        "completed",
        "completed",
        "review",
    ]


def test_api_rejects_cyclic_prerequisites():
    """Dongusel on kosul grafigi reddedilmeli."""

    payload = create_sample_payload()

    payload["prerequisite_edges"].append(
        {
            "outcome_id": "A",
            "prerequisite_id": "C",
        }
    )

    response = client.post(
        "/api/v1/learning-analyses",
        json=payload,
    )

    assert response.status_code == 422


def test_api_rejects_cross_course_outcomes():
    """Farkli derse ait kazanim reddedilmeli."""

    payload = create_sample_payload()

    payload["outcomes"][1]["course_id"] = "MATH"

    response = client.post(
        "/api/v1/learning-analyses",
        json=payload,
    )

    assert response.status_code == 422


def test_api_rejects_duplicate_questions():
    """Ayni soru iki kez puanlanmamali."""

    payload = create_sample_payload()

    payload["question_results"][1]["question_id"] = "Q1"

    response = client.post(
        "/api/v1/learning-analyses",
        json=payload,
    )

    assert response.status_code == 422


def test_api_rejects_invalid_answer_type():
    """Cevap dogrulugu boolean olmali."""

    payload = create_sample_payload()

    payload["question_results"][0]["is_correct"] = "true"

    response = client.post(
        "/api/v1/learning-analyses",
        json=payload,
    )

    assert response.status_code == 422


def test_api_rejects_empty_exam():
    """Bos sinav sonucu kabul edilmemeli."""

    payload = create_sample_payload()

    payload["question_results"] = []

    response = client.post(
        "/api/v1/learning-analyses",
        json=payload,
    )

    assert response.status_code == 422
