
import pytest

from app.domain.scoring_engine import (
    QuestionResult,
    OutcomeScore,
    ScoringEngine,
)


def test_calculate_multiple_outcome_scores():
    """Farkli kazanimlarin puanlari dogru hesaplanmali."""

    results = [
        QuestionResult("Q1", "PY1", True),
        QuestionResult("Q2", "PY1", True),
        QuestionResult("Q3", "PY1", False),
        QuestionResult("Q4", "PY1", True),
        QuestionResult("Q5", "PY1", True),
        QuestionResult("Q6", "PY2", False),
        QuestionResult("Q7", "PY2", True),
        QuestionResult("Q8", "PY2", False),
        QuestionResult("Q9", "PY2", True),
        QuestionResult("Q10", "PY2", False),
    ]

    engine = ScoringEngine()
    scores = engine.calculate_scores(results)

    assert scores == [
        OutcomeScore("PY1", 4, 5, 80.0),
        OutcomeScore("PY2", 2, 5, 40.0),
    ]


def test_all_answers_correct():
    """Tum cevaplar dogruysa basari yuzde 100 olmali."""

    results = [
        QuestionResult("Q1", "PY1", True),
        QuestionResult("Q2", "PY1", True),
    ]

    scores = ScoringEngine().calculate_scores(results)

    assert scores[0].score_percent == 100.0


def test_all_answers_wrong():
    """Tum cevaplar yanlissa basari yuzde 0 olmali."""

    results = [
        QuestionResult("Q1", "PY1", False),
        QuestionResult("Q2", "PY1", False),
    ]

    scores = ScoringEngine().calculate_scores(results)

    assert scores[0].score_percent == 0.0


def test_percentage_rounding():
    """Basari yuzdesi iki ondalik basamaga yuvarlanmali."""

    results = [
        QuestionResult("Q1", "PY1", True),
        QuestionResult("Q2", "PY1", True),
        QuestionResult("Q3", "PY1", False),
    ]

    scores = ScoringEngine().calculate_scores(results)

    assert scores[0].score_percent == 66.67


def test_deterministic_scoring():
    """Girdi sirasi degisse bile sonuc ayni olmali."""

    results = [
        QuestionResult("Q1", "PY2", True),
        QuestionResult("Q2", "PY1", False),
        QuestionResult("Q3", "PY1", True),
    ]

    engine = ScoringEngine()

    first = engine.calculate_scores(results)
    second = engine.calculate_scores(list(reversed(results)))

    assert first == second


def test_empty_exam_results():
    """Bos sinav sonuclari kabul edilmemeli."""

    engine = ScoringEngine()

    with pytest.raises(ValueError):
        engine.calculate_scores([])


def test_duplicate_question():
    """Ayni soru iki kez puanlanmamali."""

    results = [
        QuestionResult("Q1", "PY1", True),
        QuestionResult("Q1", "PY1", False),
    ]

    engine = ScoringEngine()

    with pytest.raises(ValueError):
        engine.calculate_scores(results)


def test_invalid_question_result():
    """Gecersiz soru verileri reddedilmeli."""

    with pytest.raises(ValueError):
        QuestionResult("", "PY1", True)

    with pytest.raises(ValueError):
        QuestionResult("Q1", "", True)

    with pytest.raises(TypeError):
        QuestionResult("Q1", "PY1", "yes")
