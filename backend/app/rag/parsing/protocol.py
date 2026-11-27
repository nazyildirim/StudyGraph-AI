"""DocumentParser Protocol for strategy-based document ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.rag.domain.types import ParsedDocument


class DocumentParser(Protocol):
    """Contract implemented by all document format parsers (PDF, TXT, ...)."""

    @property
    def supported_file_types(self) -> frozenset[str]: ...

    def parse(
        self,
        source: Path | str | bytes,
        *,
        source_name: str | None = None,
    ) -> ParsedDocument: ...
