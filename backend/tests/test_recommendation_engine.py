
import pytest

from app.domain.graph_engine import GraphEngine
from app.domain.learning_outcome import LearningOutcome
from app.domain.scoring_engine import OutcomeScore
from app.domain.recommendation_engine import RecommendationEngine


def create_sample_graph():
    """Testler icin ornek ogrenme grafigi olusturur."""

    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("A", "PYTHON", "Python Temelleri")
    )
    graph.add_outcome(
        LearningOutcome("B", "PYTHON", "Degiskenler")
    )
    graph.add_outcome(
        LearningOutcome("C", "PYTHON", "Donguler")
    )

    graph.add_prerequisite("B", "A")
    graph.add_prerequisite("C", "B")

    return graph


def test_completed_review_and_blocked():
    """Basari ve on kosullara gore durumlar belirlenmeli."""

    engine = RecommendationEngine(create_sample_graph())

    scores = [
        OutcomeScore("A", 9, 10, 90.0),
        OutcomeScore("B", 4, 10, 40.0),
        OutcomeScore("C", 2, 10, 20.0),
    ]

    result = engine.generate("PYTHON", scores)

    assert [item.status for item in result] == [
        "completed",
        "review",
        "blocked",
    ]

    assert result[2].missing_prerequisites == ("B",)


def test_unmeasured_outcome():
    """Olculmeyen kazanim uygun durumla onerilmeli."""

    engine = RecommendationEngine(create_sample_graph())

    scores = [
        OutcomeScore("A", 10, 10, 100.0),
    ]

    result = engine.generate("PYTHON", scores)

    assert result[0].status == "completed"
    assert result[1].status == "study"
    assert result[1].score_percent is None
    assert result[2].status == "blocked"


def test_multiple_missing_prerequisites():
    """Birden fazla on kosul dogru degerlendirilmeli."""

    graph = GraphEngine()

    for outcome_id in ("A", "B", "C"):
        graph.add_outcome(
            LearningOutcome(outcome_id, "PYTHON", outcome_id)
        )

    graph.add_prerequisite("C", "A")
    graph.add_prerequisite("C", "B")

    engine = RecommendationEngine(graph)

    scores = [
        OutcomeScore("A", 9, 10, 90.0),
        OutcomeScore("B", 3, 10, 30.0),
        OutcomeScore("C", 2, 10, 20.0),
    ]

    result = engine.generate("PYTHON", scores)

    assert result[2].status == "blocked"
    assert result[2].missing_prerequisites == ("B",)


def test_retest_updates_recommendations():
    """Tekrar sinavi sonrasinda oneriler degismeli."""

    engine = RecommendationEngine(create_sample_graph())

    initial_scores = [
        OutcomeScore("A", 4, 10, 40.0),
        OutcomeScore("B", 4, 10, 40.0),
        OutcomeScore("C", 2, 10, 20.0),
    ]

    initial = engine.generate("PYTHON", initial_scores)

    assert [item.status for item in initial] == [
        "review",
        "blocked",
        "blocked",
    ]

    updated_scores = [
        OutcomeScore("A", 9, 10, 90.0),
        OutcomeScore("B", 8, 10, 80.0),
        OutcomeScore("C", 2, 10, 20.0),
    ]

    updated = engine.generate("PYTHON", updated_scores)

    assert [item.status for item in updated] == [
        "completed",
        "completed",
        "review",
    ]


def test_mastery_threshold():
    """Basari esigine esit puan tamamlanmis sayilmali."""

    engine = RecommendationEngine(
        create_sample_graph(),
        mastery_threshold=70.0,
    )

    scores = [
        OutcomeScore("A", 7, 10, 70.0),
        OutcomeScore("B", 6, 10, 60.0),
    ]

    result = engine.generate("PYTHON", scores)

    assert result[0].status == "completed"
    assert result[1].status == "review"
    assert result[2].status == "blocked"


def test_deterministic_recommendations():
    """Puanlarin sirasi sonucu degistirmemeli."""

    engine = RecommendationEngine(create_sample_graph())

    scores = [
        OutcomeScore("A", 9, 10, 90.0),
        OutcomeScore("B", 4, 10, 40.0),
        OutcomeScore("C", 2, 10, 20.0),
    ]

    first = engine.generate("PYTHON", scores)
    second = engine.generate("PYTHON", list(reversed(scores)))

    assert first == second


def test_independent_student_results():
    """Farkli ogrencilerin sonuclari birbirine karismamali."""

    engine = RecommendationEngine(create_sample_graph())

    student_one = [
        OutcomeScore("A", 10, 10, 100.0),
        OutcomeScore("B", 10, 10, 100.0),
        OutcomeScore("C", 10, 10, 100.0),
    ]

    student_two = [
        OutcomeScore("A", 0, 10, 0.0),
        OutcomeScore("B", 0, 10, 0.0),
        OutcomeScore("C", 0, 10, 0.0),
    ]

    first = engine.generate("PYTHON", student_one)
    second = engine.generate("PYTHON", student_two)

    assert all(item.status == "completed" for item in first)

    assert [item.status for item in second] == [
        "review",
        "blocked",
        "blocked",
    ]


def test_duplicate_outcome_scores():
    """Ayni kazanim icin tekrarlanan puan reddedilmeli."""

    engine = RecommendationEngine(create_sample_graph())

    scores = [
        OutcomeScore("A", 8, 10, 80.0),
        OutcomeScore("A", 5, 10, 50.0),
    ]

    with pytest.raises(ValueError):
        engine.generate("PYTHON", scores)


def test_reject_scores_from_another_course():
    """Baska derse ait puanlar kabul edilmemeli."""

    engine = RecommendationEngine(create_sample_graph())

    scores = [
        OutcomeScore("M1", 8, 10, 80.0),
    ]

    with pytest.raises(ValueError):
        engine.generate("PYTHON", scores)


def test_invalid_inputs():
    """Gecersiz esik, veri tipi ve puan reddedilmeli."""

    graph = create_sample_graph()

    with pytest.raises(ValueError):
        RecommendationEngine(graph, mastery_threshold=120)

    with pytest.raises(ValueError):
        RecommendationEngine(graph, mastery_threshold=True)

    engine = RecommendationEngine(graph)

    with pytest.raises(TypeError):
        engine.generate("PYTHON", "invalid")

    with pytest.raises(ValueError):
        engine.generate(
            "PYTHON",
            [OutcomeScore("A", 1, 1, 101.0)],
        )
