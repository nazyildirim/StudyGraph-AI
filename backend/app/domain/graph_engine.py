
from heapq import heapify, heappop, heappush

from app.domain.learning_outcome import LearningOutcome


class GraphEngine:
    """Ders kazanımları arasındaki ön koşul ilişkilerini yönetir."""

    def __init__(self):
        self._outcomes: dict[str, LearningOutcome] = {}
        self._prerequisites: dict[str, set[str]] = {}

    def add_outcome(self, outcome: LearningOutcome) -> None:
        """Sisteme yeni bir kazanım ekler."""

        if not isinstance(outcome, LearningOutcome):
            raise TypeError("Geçerli bir LearningOutcome nesnesi gerekli.")

        if outcome.id in self._outcomes:
            if self._outcomes[outcome.id] != outcome:
                raise ValueError("Bu kimlik başka bir kazanıma ait.")
            return

        self._outcomes[outcome.id] = outcome
        self._prerequisites[outcome.id] = set()

    def add_prerequisite(
        self, outcome_id: str, prerequisite_id: str
    ) -> None:
        """İki kazanım arasında ön koşul ilişkisi kurar."""

        if outcome_id not in self._outcomes:
            raise ValueError("Kazanım bulunamadı.")

        if prerequisite_id not in self._outcomes:
            raise ValueError("Ön koşul kazanımı bulunamadı.")

        outcome = self._outcomes[outcome_id]
        prerequisite = self._outcomes[prerequisite_id]

        if outcome.course_id != prerequisite.course_id:
            raise ValueError(
                "Farklı derslerin kazanımları bağlanamaz."
            )

        if self._depends_on(prerequisite_id, outcome_id):
            raise ValueError(
                "Döngüsel ön koşul ilişkisi oluşturulamaz."
            )

        self._prerequisites[outcome_id].add(prerequisite_id)

    def get_prerequisites(self, outcome_id: str) -> list[str]:
        """Bir kazanımın doğrudan ön koşullarını getirir."""

        if outcome_id not in self._outcomes:
            raise ValueError("Kazanım bulunamadı.")

        return sorted(self._prerequisites[outcome_id])

    def _depends_on(self, start: str, target: str) -> bool:
        """İki kazanım arasında bağımlılık yolu arar."""

        visited = set()
        stack = [start]

        while stack:
            current = stack.pop()

            if current == target:
                return True

            if current in visited:
                continue

            visited.add(current)
            stack.extend(self._prerequisites[current])

        return False

    def get_learning_order(self, course_id: str) -> list[str]:
        """Bir dersin kazanımlarını ön koşul sırasına koyar."""

        if not isinstance(course_id, str) or not course_id.strip():
            raise ValueError("Ders kimliği boş olamaz.")

        nodes = {
            outcome_id
            for outcome_id, outcome in self._outcomes.items()
            if outcome.course_id == course_id
        }

        indegree = {
            node: len(self._prerequisites[node])
            for node in nodes
        }

        dependents = {node: [] for node in nodes}

        for node in nodes:
            for prerequisite in self._prerequisites[node]:
                dependents[prerequisite].append(node)

        ready = [
            node for node in nodes
            if indegree[node] == 0
        ]

        heapify(ready)
        order = []

        while ready:
            current = heappop(ready)
            order.append(current)

            for dependent in dependents[current]:
                indegree[dependent] -= 1

                if indegree[dependent] == 0:
                    heappush(ready, dependent)

        if len(order) != len(nodes):
            raise ValueError("Grafikte döngü tespit edildi.")

        return order
