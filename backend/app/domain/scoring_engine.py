
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True, slots=True)
class QuestionResult:
    """Bir sınav sorusunun değerlendirme sonucu."""

    question_id: str
    outcome_id: str
    is_correct: bool

    def __post_init__(self):
        for field_name in ("question_id", "outcome_id"):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} boş olamaz."
                )

        if not isinstance(self.is_correct, bool):
            raise TypeError(
                "is_correct True veya False olmalıdır."
            )


@dataclass(frozen=True, slots=True)
class OutcomeScore:
    """Bir kazanım için hesaplanan başarı sonucu."""

    outcome_id: str
    correct_count: int
    question_count: int
    score_percent: float


class ScoringEngine:
    """Sınav sonuçlarını kazanım bazında puanlar."""

    def calculate_scores(
        self, results: list[QuestionResult]
    ) -> list[OutcomeScore]:
        """Her kazanım için deterministik başarı puanı hesaplar."""

        if not isinstance(results, list) or not results:
            raise ValueError(
                "Sınav sonuçları boş olamaz ve liste olmalıdır."
            )

        grouped: dict[str, dict[str, int]] = {}
        seen_questions: set[str] = set()

        for result in results:
            if not isinstance(result, QuestionResult):
                raise TypeError(
                    "Tüm sonuçlar QuestionResult tipinde olmalıdır."
                )

            if result.question_id in seen_questions:
                raise ValueError(
                    "Aynı soru bir sınavda tekrar değerlendirilemez."
                )

            seen_questions.add(result.question_id)

            if result.outcome_id not in grouped:
                grouped[result.outcome_id] = {
                    "correct": 0,
                    "total": 0
                }

            grouped[result.outcome_id]["total"] += 1

            if result.is_correct:
                grouped[result.outcome_id]["correct"] += 1

        scores = []

        for outcome_id in sorted(grouped):
            data = grouped[outcome_id]

            correct = data["correct"]
            total = data["total"]

            percentage = (
                Decimal(correct)
                * Decimal(100)
                / Decimal(total)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            scores.append(
                OutcomeScore(
                    outcome_id=outcome_id,
                    correct_count=correct,
                    question_count=total,
                    score_percent=float(percentage)
                )
            )

        return scores
