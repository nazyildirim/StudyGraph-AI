
import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
API_URL = "/api/v1/learning-analyses"


def sample_payload():
    """API dogrulama testleri icin gecerli ornek veri."""
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
            {"outcome_id": "B", "prerequisite_id": "A"},
            {"outcome_id": "C", "prerequisite_id": "B"},
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
        ],
        "mastery_threshold": 70.0,
    }


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("course_id", "   "),
        ("outcomes", []),
        ("question_results", []),
        ("mastery_threshold", -1),
        ("mastery_threshold", 101),
        ("mastery_threshold", None),
    ],
)
def test_invalid_required_inputs(field, invalid_value):
    """Bos veya sinir disi veriler reddedilmeli."""
    payload = sample_payload()
    payload[field] = invalid_value

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_unexpected_field():
    """Tanimlanmayan alanlar kabul edilmemeli."""
    payload = sample_payload()
    payload["outcomes"][0]["admin_access"] = True

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_blank_outcome_title():
    """Kazanimin basligi bosluklardan olusamaz."""
    payload = sample_payload()
    payload["outcomes"][0]["title"] = "   "

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_non_boolean_answer():
    """Soru dogrulugu sayisal deger olamaz."""
    payload = sample_payload()
    payload["question_results"][0]["is_correct"] = 1

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_unknown_question_outcome():
    """Sinav sonucu tanimsiz kazanima ait olamaz."""
    payload = sample_payload()
    payload["question_results"][0]["outcome_id"] = "UNKNOWN"

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_unknown_prerequisite():
    """Olmayan bir on kosula baglanti kurulamamali."""
    payload = sample_payload()
    payload["prerequisite_edges"].append(
        {
            "outcome_id": "C",
            "prerequisite_id": "UNKNOWN",
        }
    )

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_rejects_conflicting_outcome_ids():
    """Ayni kimlikte farkli kazanimlar kabul edilmemeli."""
    payload = sample_payload()
    payload["outcomes"].append(
        {
            "id": "A",
            "course_id": "PYTHON",
            "title": "Farkli Kazanim",
        }
    )

    response = client.post(API_URL, json=payload)

    assert response.status_code == 422


def test_unmeasured_outcome_can_be_studied():
    """Olculmeyen ve on kosulu tamamlanan kazanim calisilabilir."""
    payload = sample_payload()
    payload["question_results"][1]["is_correct"] = True

    response = client.post(API_URL, json=payload)

    assert response.status_code == 200

    recommendations = {
        item["outcome_id"]: item
        for item in response.json()["recommendations"]
    }

    assert recommendations["C"]["status"] == "study"
    assert recommendations["C"]["score_percent"] is None


def test_exact_mastery_threshold():
    """Tam yuzde 70 puan basarili sayilmali."""
    payload = sample_payload()
    payload["question_results"] = [
        {
            "question_id": f"Q{i}",
            "outcome_id": "A",
            "is_correct": i <= 7,
        }
        for i in range(1, 11)
    ]

    response = client.post(API_URL, json=payload)

    assert response.status_code == 200

    recommendations = {
        item["outcome_id"]: item
        for item in response.json()["recommendations"]
    }

    assert recommendations["A"]["score_percent"] == 70.0
    assert recommendations["A"]["status"] == "completed"


def test_question_order_does_not_change_analysis():
    """Sorularin gelis sirasi analiz sonucunu degistirmemeli."""
    payload = sample_payload()

    first = client.post(API_URL, json=payload)

    payload["question_results"].reverse()
    second = client.post(API_URL, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
