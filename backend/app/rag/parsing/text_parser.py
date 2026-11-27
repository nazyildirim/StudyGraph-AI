"""Plain-text (TXT) document parser for RAG ingestion."""

from __future__ import annotations

from pathlib import Path

from app.rag.domain.types import (
    BlockKind,
    DocumentBlock,
    ExtractionReport,
    ParsedDocument,
    ParsedPage,
)
from app.rag.parsing.code_heuristics import (
    infer_code_language,
    looks_like_code_line,
    looks_like_heading_text,
)
from app.rag.parsing.errors import EmptyDocumentError, InvalidDocumentError

_SUPPORTED_TYPES = frozenset({"text/plain"})


class PlainTextParser:
    """Parses UTF-8 / UTF-8-BOM plain-text files while preserving code indentation."""

    @property
    def supported_file_types(self) -> frozenset[str]:
        return _SUPPORTED_TYPES

    def parse(
        self,
        source: Path | str | bytes,
        *,
        source_name: str | None = None,
        page_number: int = 1,
    ) -> ParsedDocument:
        if page_number < 1:
            raise InvalidDocumentError("page_number must be >= 1.")
        raw_bytes, resolved_name = _read_source_bytes(source, source_name)
        if b"\x00" in raw_bytes:
            raise InvalidDocumentError(
                "Plain text source contains NUL bytes and appears to be binary."
            )
        try:
            decoded = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise InvalidDocumentError(
                "Plain text source is not valid UTF-8."
            ) from error

        normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            report = ExtractionReport(
                total_pages=1,
                empty_pages=(page_number,),
                errors=("Metin dosyasi bos veya yalnizca bosluk iceriyor.",),
            )
            raise EmptyDocumentError(
                "Plain text source is empty.",
                report=report,
            )

        blocks = tuple(_segment_text_into_blocks(normalized, page_number=page_number))
        code_count = sum(1 for block in blocks if block.kind is BlockKind.CODE)
        page = ParsedPage(
            page_number=page_number,
            text=normalized.strip("\n"),
            blocks=blocks,
            image_count=0,
            is_empty=False,
            suspected_scanned=False,
        )
        report = ExtractionReport(
            total_pages=1,
            text_extracted_pages=(page_number,),
            code_block_count=code_count,
        )
        return ParsedDocument(
            source_name=resolved_name,
            file_type="text/plain",
            pages=(page,),
            report=report,
        )


def _read_source_bytes(
    source: Path | str | bytes,
    source_name: str | None,
) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        return source, source_name or "inline.txt"
    path = Path(source)
    if not path.is_file():
        raise InvalidDocumentError(f"Text file not found: {path}")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise InvalidDocumentError(f"Unable to read text file: {path}") from error
    return data, source_name or path.name


def _segment_text_into_blocks(text: str, *, page_number: int) -> list[DocumentBlock]:
    lines = text.split("\n")
    blocks: list[DocumentBlock] = []
    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            idx += 1
            continue

        # 1. Fenced code block (```lang ... ```)
        if stripped.startswith("```"):
            lang_hint = stripped[3:].strip().lower() or None
            idx += 1
            code_lines: list[str] = []
            while idx < total and not lines[idx].strip().startswith("```"):
                code_lines.append(lines[idx].rstrip())
                idx += 1
            if idx < total and lines[idx].strip().startswith("```"):
                idx += 1
            code_text = "\n".join(code_lines).strip("\n")
            if code_text.strip():
                blocks.append(
                    DocumentBlock(
                        kind=BlockKind.CODE,
                        text=code_text,
                        page_number=page_number,
                        language_hint=lang_hint or infer_code_language(code_text),
                    )
                )
            continue

        # 2. Markdown or numbered heading on its own line
        if stripped.startswith("#") and not stripped.startswith("#include") and not stripped.startswith("#define"):
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.HEADING,
                    text=stripped.lstrip("#").strip() or stripped,
                    page_number=page_number,
                )
            )
            idx += 1
            continue

        # 3. Unfenced code block (C/Python code line + indented continuation)
        if looks_like_code_line(line):
            code_lines = [line.rstrip()]
            idx += 1
            while idx < total:
                nxt = lines[idx]
                if not nxt.strip():
                    # Include a single blank line only if followed by more code.
                    if idx + 1 < total and (
                        looks_like_code_line(lines[idx + 1])
                        or lines[idx + 1].startswith(("    ", "\t"))
                    ):
                        code_lines.append("")
                        idx += 1
                        continue
                    break
                if looks_like_code_line(nxt) or nxt.startswith(("  ", "\t")):
                    code_lines.append(nxt.rstrip())
                    idx += 1
                    continue
                break
            code_text = "\n".join(code_lines).strip("\n")
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.CODE,
                    text=code_text,
                    page_number=page_number,
                    language_hint=infer_code_language(code_text),
                )
            )
            continue

        # 4. Paragraph (or short standalone numbered heading)
        para_lines: list[str] = [stripped]
        idx += 1
        while idx < total:
            nxt = lines[idx]
            nxt_stripped = nxt.strip()
            if not nxt_stripped:
                break
            if nxt_stripped.startswith("```") or looks_like_code_line(nxt):
                break
            if nxt_stripped.startswith("#") and not nxt_stripped.startswith(
                ("#include", "#define")
            ):
                break
            para_lines.append(nxt_stripped)
            idx += 1

        if len(para_lines) == 1 and looks_like_heading_text(para_lines[0]):
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.HEADING,
                    text=para_lines[0],
                    page_number=page_number,
                )
            )
        else:
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.PARAGRAPH,
                    text="\n".join(para_lines),
                    page_number=page_number,
                )
            )

    return blocks
