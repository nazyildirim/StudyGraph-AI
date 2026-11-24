
import pytest

from app.domain.learning_outcome import LearningOutcome
from app.domain.scoring_engine import QuestionResult
from app.services.learning_analysis_service import LearningAnalysisService


def create_sample_data():
    """Ornek ders, kazanim ve on kosul verileri."""

    outcomes = [
        LearningOutcome("A", "PYTHON", "Python Temelleri"),
        LearningOutcome("B", "PYTHON", "Degiskenler"),
        LearningOutcome("C", "PYTHON", "Donguler"),
    ]

    prerequisites = [
        ("B", "A"),
        ("C", "B"),
    ]

    return outcomes, prerequisites


def test_complete_learning_analysis():
    """Uc algoritma birlikte dogru calismali."""

    outcomes, prerequisites = create_sample_data()

    results = [
        QuestionResult("Q1", "A", True),
        QuestionResult("Q2", "A", True),
        QuestionResult("Q3", "B", True),
        QuestionResult("Q4", "B", False),
        QuestionResult("Q5", "C", False),
        QuestionResult("Q6", "C", False),
    ]

    service = LearningAnalysisService()

    analysis = service.analyze(
        course_id="PYTHON",
        outcomes=outcomes,
        prerequisite_edges=prerequisites,
        question_results=results,
    )

    assert analysis.course_id == "PYTHON"
    assert analysis.learning_order == ("A", "B", "C")

    scores = {
        score.outcome_id: score.score_percent
        for score in analysis.scores
    }

    assert scores == {
        "A": 100.0,
        "B": 50.0,
        "C": 0.0,
    }

    assert [
        item.status for item in analysis.recommendations
    ] == [
        "completed",
        "review",
        "blocked",
    ]


def test_retest_updates_learning_analysis():
    """Tekrar sinavinda yeni puanlarla oneriler degismeli."""

    outcomes, prerequisites = create_sample_data()

    service = LearningAnalysisService()

    initial_results = [
        QuestionResult("Q1", "A", False),
        QuestionResult("Q2", "B", False),
        QuestionResult("Q3", "C", False),
    ]

    initial = service.analyze(
        "PYTHON",
        outcomes,
        prerequisites,
        initial_results,
    )

    assert [
        item.status for item in initial.recommendations
    ] == [
        "review",
        "blocked",
        "blocked",
    ]

    updated_results = [
        QuestionResult("Q1", "A", True),
        QuestionResult("Q2", "B", True),
        QuestionResult("Q3", "C", False),
    ]

    updated = service.analyze(
        "PYTHON",
        outcomes,
        prerequisites,
        updated_results,
    )

    assert [
        item.status for item in updated.recommendations
    ] == [
        "completed",
        "completed",
        "review",
    ]


def test_multiple_prerequisites_analysis():
    """Birden fazla on kosul birlikte degerlendirilmeli."""

    outcomes = [
        LearningOutcome("A", "MATH", "Fonksiyonlar"),
        LearningOutcome("B", "MATH", "Limit"),
        LearningOutcome("C", "MATH", "Turev"),
    ]

    prerequisites = [
        ("C", "A"),
        ("C", "B"),
    ]

    results = [
        QuestionResult("Q1", "A", True),
        QuestionResult("Q2", "B", False),
        QuestionResult("Q3", "C", False),
    ]

    analysis = LearningAnalysisService().analyze(
        "MATH",
        outcomes,
        prerequisites,
        results,
    )

    recommendations = {
        item.outcome_id: item
        for item in analysis.recommendations
    }

    assert recommendations["A"].status == "completed"
    assert recommendations["B"].status == "review"
    assert recommendations["C"].status == "blocked"
    assert recommendations["C"].missing_prerequisites == ("B",)


def test_cycle_rejected_during_analysis():
    """Dongusel grafik analiz edilmemeli."""

    outcomes, _ = create_sample_data()

    prerequisites = [
        ("B", "A"),
        ("C", "B"),
        ("A", "C"),
    ]

    results = [
        QuestionResult("Q1", "A", True),
    ]

    with pytest.raises(ValueError):
        LearningAnalysisService().analyze(
            "PYTHON",
            outcomes,
            prerequisites,
            results,
        )


def test_cross_course_outcome_rejected():
    """Farkli derse ait kazanim kabul edilmemeli."""

    outcomes = [
        LearningOutcome("A", "PYTHON", "Degiskenler"),
        LearningOutcome("B", "MATH", "Fonksiyonlar"),
    ]

    results = [
        QuestionResult("Q1", "A", True),
    ]

    with pytest.raises(ValueError):
        LearningAnalysisService().analyze(
            "PYTHON",
            outcomes,
            [],
            results,
        )


def test_independent_learning_analyses():
    """Farkli analizlerin sonuclari birbirine karismamali."""

    outcomes, prerequisites = create_sample_data()

    service = LearningAnalysisService()

    successful_results = [
        QuestionResult("Q1", "A", True),
        QuestionResult("Q2", "B", True),
        QuestionResult("Q3", "C", True),
    ]

    unsuccessful_results = [
        QuestionResult("Q1", "A", False),
        QuestionResult("Q2", "B", False),
        QuestionResult("Q3", "C", False),
    ]

    first = service.analyze(
        "PYTHON",
        outcomes,
        prerequisites,
        successful_results,
    )

    second = service.analyze(
        "PYTHON",
        outcomes,
        prerequisites,
        unsuccessful_results,
    )

    assert all(
        item.status == "completed"
        for item in first.recommendations
    )

    assert [
        item.status for item in second.recommendations
    ] == [
        "review",
        "blocked",
        "blocked",
    ]
