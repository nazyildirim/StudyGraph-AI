
from dataclasses import dataclass

from app.domain.graph_engine import GraphEngine
from app.domain.learning_outcome import LearningOutcome
from app.domain.scoring_engine import (
    ScoringEngine,
    QuestionResult,
    OutcomeScore,
)
from app.domain.recommendation_engine import (
    RecommendationEngine,
    LearningRecommendation,
)


@dataclass(frozen=True, slots=True)
class LearningAnalysisResult:
    """Ogrenme analizi sonucunu temsil eder."""

    course_id: str
    learning_order: tuple[str, ...]
    scores: tuple[OutcomeScore, ...]
    recommendations: tuple[LearningRecommendation, ...]


class LearningAnalysisService:
    """Ogrenme analizi algoritmalarini birlikte calistirir."""

    def __init__(
        self,
        scoring_engine: ScoringEngine | None = None,
    ):
        self._scoring_engine = (
            scoring_engine
            if scoring_engine is not None
            else ScoringEngine()
        )

    def analyze(
        self,
        course_id: str,
        outcomes: list[LearningOutcome],
        prerequisite_edges: list[tuple[str, str]],
        question_results: list[QuestionResult],
        mastery_threshold: float = 70.0,
    ) -> LearningAnalysisResult:
        """Bir ders icin ogrenme analizini gerceklestirir."""

        if not isinstance(course_id, str) or not course_id.strip():
            raise ValueError("Gecerli bir ders kimligi gerekli.")

        if not isinstance(outcomes, list) or not outcomes:
            raise ValueError("Dersin kazanimlari bos olamaz.")

        if not isinstance(prerequisite_edges, list):
            raise TypeError("On kosul iliskileri liste olmalidir.")

        graph = GraphEngine()

        # 1. Kazanim grafigini olustur.
        for outcome in outcomes:
            if not isinstance(outcome, LearningOutcome):
                raise TypeError("Gecersiz kazanim nesnesi.")

            if outcome.course_id != course_id:
                raise ValueError(
                    "Kazanim farkli bir derse ait."
                )

            graph.add_outcome(outcome)

        # 2. On kosul iliskilerini kur.
        for outcome_id, prerequisite_id in prerequisite_edges:
            graph.add_prerequisite(
                outcome_id,
                prerequisite_id,
            )

        # 3. Gecerli ogrenme sirasini hesapla.
        learning_order = graph.get_learning_order(course_id)

        # 4. Sinav sonuclarini puanla.
        scores = self._scoring_engine.calculate_scores(
            question_results
        )

        # 5. Kisisellestirilmis onerileri olustur.
        recommendation_engine = RecommendationEngine(
            graph=graph,
            mastery_threshold=mastery_threshold,
        )

        recommendations = recommendation_engine.generate(
            course_id=course_id,
            scores=scores,
        )

        # 6. Analiz sonucunu dondur.
        return LearningAnalysisResult(
            course_id=course_id,
            learning_order=tuple(learning_order),
            scores=tuple(scores),
            recommendations=tuple(recommendations),
        )
