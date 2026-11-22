
from dataclasses import dataclass

from app.domain.graph_engine import GraphEngine
from app.domain.scoring_engine import OutcomeScore


@dataclass(frozen=True, slots=True)
class LearningRecommendation:
    """Ogrencinin bir kazanim icin ogrenme durumu."""

    outcome_id: str
    status: str
    score_percent: float | None
    missing_prerequisites: tuple[str, ...]


class RecommendationEngine:
    """Sinav puanlarina ve on kosullara gore oneriler olusturur."""

    def __init__(
        self,
        graph: GraphEngine,
        mastery_threshold: float = 70.0,
    ):
        if not isinstance(graph, GraphEngine):
            raise TypeError("Gecerli bir GraphEngine gerekli.")

        if (
            isinstance(mastery_threshold, bool)
            or not isinstance(mastery_threshold, (int, float))
            or not 0 <= mastery_threshold <= 100
        ):
            raise ValueError("Basari esigi 0-100 arasinda olmali.")

        self._graph = graph
        self._mastery_threshold = mastery_threshold

    def generate(
        self,
        course_id: str,
        scores: list[OutcomeScore],
    ) -> list[LearningRecommendation]:
        """Bir ders icin kisisellestirilmis ogrenme plani uretir."""

        if not isinstance(scores, list):
            raise TypeError("Puanlar liste olarak verilmelidir.")

        learning_order = self._graph.get_learning_order(course_id)
        valid_outcomes = set(learning_order)

        scores_by_outcome: dict[str, OutcomeScore] = {}

        for score in scores:
            if not isinstance(score, OutcomeScore):
                raise TypeError("Gecersiz basari puani nesnesi.")

            if score.outcome_id not in valid_outcomes:
                raise ValueError(
                    "Puan bu derse ait olmayan bir kazanima ait."
                )

            if score.outcome_id in scores_by_outcome:
                raise ValueError(
                    "Ayni kazanim icin birden fazla puan var."
                )

            if not 0 <= score.score_percent <= 100:
                raise ValueError("Basari puani 0-100 arasinda olmali.")

            scores_by_outcome[score.outcome_id] = score

        mastered = {
            outcome_id
            for outcome_id, score in scores_by_outcome.items()
            if score.score_percent >= self._mastery_threshold
        }

        recommendations = []

        for outcome_id in learning_order:
            score = scores_by_outcome.get(outcome_id)

            if outcome_id in mastered:
                status = "completed"
                missing = ()

            else:
                prerequisites = self._graph.get_prerequisites(
                    outcome_id
                )

                missing = tuple(
                    prerequisite
                    for prerequisite in prerequisites
                    if prerequisite not in mastered
                )

                if missing:
                    status = "blocked"
                elif score is None:
                    status = "study"
                else:
                    status = "review"

            recommendations.append(
                LearningRecommendation(
                    outcome_id=outcome_id,
                    status=status,
                    score_percent=(
                        score.score_percent
                        if score is not None
                        else None
                    ),
                    missing_prerequisites=missing,
                )
            )

        return recommendations
