
import pytest

from app.domain.graph_engine import GraphEngine
from app.domain.learning_outcome import LearningOutcome


def test_add_outcomes():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("PY1", "PYTHON", "Degiskenler")
    )

    assert graph.get_prerequisites("PY1") == []


def test_multiple_prerequisites():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("PY1", "PYTHON", "Degiskenler")
    )
    graph.add_outcome(
        LearningOutcome("PY2", "PYTHON", "Kosullar")
    )
    graph.add_outcome(
        LearningOutcome("PY3", "PYTHON", "Donguler")
    )

    graph.add_prerequisite("PY3", "PY1")
    graph.add_prerequisite("PY3", "PY2")

    assert graph.get_prerequisites("PY3") == ["PY1", "PY2"]


def test_cycle_detection():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("A", "PYTHON", "Konu A")
    )
    graph.add_outcome(
        LearningOutcome("B", "PYTHON", "Konu B")
    )

    graph.add_prerequisite("B", "A")

    with pytest.raises(ValueError):
        graph.add_prerequisite("A", "B")


def test_cross_course_restriction():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("A", "PYTHON", "Degiskenler")
    )
    graph.add_outcome(
        LearningOutcome("B", "MATH", "Fonksiyonlar")
    )

    with pytest.raises(ValueError):
        graph.add_prerequisite("A", "B")


def test_learning_order():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("A", "PYTHON", "Python Temelleri")
    )
    graph.add_outcome(
        LearningOutcome("B", "PYTHON", "Degiskenler")
    )
    graph.add_outcome(
        LearningOutcome("C", "PYTHON", "Kosullar")
    )
    graph.add_outcome(
        LearningOutcome("D", "PYTHON", "Donguler")
    )

    graph.add_prerequisite("B", "A")
    graph.add_prerequisite("C", "A")
    graph.add_prerequisite("D", "B")
    graph.add_prerequisite("D", "C")

    order = graph.get_learning_order("PYTHON")

    assert order == ["A", "B", "C", "D"]


def test_learning_order_separates_courses():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("PY1", "PYTHON", "Temeller")
    )
    graph.add_outcome(
        LearningOutcome("PY2", "PYTHON", "Fonksiyonlar")
    )
    graph.add_outcome(
        LearningOutcome("M1", "MATH", "Matematik")
    )

    graph.add_prerequisite("PY2", "PY1")

    assert graph.get_learning_order("PYTHON") == [
        "PY1", "PY2"
    ]

    assert graph.get_learning_order("MATH") == ["M1"]


def test_self_dependency():
    graph = GraphEngine()

    graph.add_outcome(
        LearningOutcome("A", "PYTHON", "Temeller")
    )

    with pytest.raises(ValueError):
        graph.add_prerequisite("A", "A")


def test_invalid_course_id():
    graph = GraphEngine()

    with pytest.raises(ValueError):
        graph.get_learning_order("")
