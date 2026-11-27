"""Extractive fallback LLMClient used only when the real LLM is unavailable.

Never pretends to be a generative LLM answer: explicitly informs the student
that backup extractive mode is active and quotes only retrieved course chunks
with their exact server-issued source IDs.
"""

from __future__ import annotations

from app.rag.generation.types import LLMRequest, LLMResponse

EXTRACTIVE_MODEL_NAME = "extractive-fallback"
EXTRACTIVE_NOTICE = (
    "[Yedek Çıkarımsal Mod] Yerel yapay zekâ modeli şu anda erişilemediği için "
    "bu yanıt üretken model yerine doğrudan ders materyallerinden alınan ilgili "
    "parçalarla oluşturulmuştur:"
)


class ExtractiveLLMClient:
    """Deterministic extractive backup implementing `LLMClient`."""

    def __init__(self, *, max_sources: int = 3) -> None:
        if max_sources <= 0:
            raise ValueError("max_sources must be > 0.")
        self._max_sources = max_sources

    @property
    def model_name(self) -> str:
        return EXTRACTIVE_MODEL_NAME

    def generate(self, request: LLMRequest) -> LLMResponse:
        selected = request.sources[: self._max_sources]
        if not selected:
            return LLMResponse(
                sufficient_context=False,
                answer=(
                    "Yüklenen ders materyallerinde bu soruyla ilgili yeterli "
                    "kaynak bulunamadı."
                ),
                cited_source_ids=(),
                model_name=self.model_name,
                is_fallback=True,
            )

        lines = [EXTRACTIVE_NOTICE, ""]
        cited_ids: list[str] = []
        for entry in selected:
            page_info = (
                f"s. {entry.chunk.page_start}"
                if entry.chunk.page_start is not None
                else "sayfa belirtilmemiş"
            )
            lines.append(
                f"- [{entry.source_id}] ({entry.chunk.material_title}, {page_info}): "
                f"{entry.chunk.content.strip()}"
            )
            cited_ids.append(entry.source_id)

        return LLMResponse(
            sufficient_context=True,
            answer="\n".join(lines),
            cited_source_ids=tuple(cited_ids),
            model_name=self.model_name,
            is_fallback=True,
        )
