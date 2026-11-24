
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LearningOutcome:
    """Bir derse ait ogrenme kazanimi."""

    id: str
    course_id: str
    title: str
    description: str = ""

    def __post_init__(self):
        required_fields = {
            "id": self.id,
            "course_id": self.course_id,
            "title": self.title,
        }

        for field_name, value in required_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} bos olamaz."
                )
