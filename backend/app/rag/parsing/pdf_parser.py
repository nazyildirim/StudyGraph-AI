"""PDF document parser powered by pdfplumber (MIT).

Preserves page numbers, reading order (including two-column heuristic),
headings, paragraphs, and C/Python code block indentation using character
font and coordinate metadata. Reports empty pages, image-bearing pages, and
heuristically suspected scanned pages in `ExtractionReport`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import io
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSEOF, PSSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from app.rag.domain.types import (
    BlockKind,
    DocumentBlock,
    ExtractionReport,
    ParsedDocument,
    ParsedPage,
)
from app.rag.parsing.code_heuristics import (
    infer_code_language,
    is_bold_font,
    is_monospace_font,
    looks_like_code_line,
    looks_like_heading_text,
)
from app.rag.parsing.errors import (
    EmptyDocumentError,
    EncryptedDocumentError,
    InvalidDocumentError,
)

_SUPPORTED_TYPES = frozenset({"application/pdf"})
_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True, slots=True)
class _VisualLine:
    """A single reconstructed visual line with layout and font statistics."""

    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    font_size: float
    is_monospace: bool
    is_bold: bool


class PdfDocumentParser:
    """Layout-aware PDF parser implementing `DocumentParser`.

    Note: Layout reconstruction, multi-column detection, code-block detection,
    and suspected-scanned-page detection are heuristic and cannot be guaranteed
    100% accurate on arbitrary PDFs. OCR and visual/diagram interpretation are
    intentionally out of scope.
    """

    def __init__(
        self,
        *,
        scanned_text_threshold: int = 30,
        line_y_tolerance: float = 3.0,
        heading_size_ratio: float = 1.18,
        max_pages: int = 200,
        max_extracted_chars: int = 500_000,
    ) -> None:
        if scanned_text_threshold < 0:
            raise ValueError("scanned_text_threshold must be >= 0.")
        if line_y_tolerance <= 0:
            raise ValueError("line_y_tolerance must be > 0.")
        if heading_size_ratio <= 1.0:
            raise ValueError("heading_size_ratio must be > 1.0.")
        if max_pages <= 0:
            raise ValueError("max_pages must be > 0.")
        if max_extracted_chars <= 0:
            raise ValueError("max_extracted_chars must be > 0.")
        self._scanned_text_threshold = scanned_text_threshold
        self._line_y_tolerance = line_y_tolerance
        self._heading_size_ratio = heading_size_ratio
        self._max_pages = max_pages
        self._max_extracted_chars = max_extracted_chars

    @property
    def supported_file_types(self) -> frozenset[str]:
        return _SUPPORTED_TYPES

    def parse(
        self,
        source: Path | str | bytes,
        *,
        source_name: str | None = None,
    ) -> ParsedDocument:
        raw_bytes, resolved_name = _load_pdf_bytes(source, source_name)
        if not raw_bytes.lstrip()[:5] == _PDF_MAGIC:
            raise InvalidDocumentError(
                "Input does not start with a valid %PDF- header."
            )

        pages: list[ParsedPage] = []
        text_extracted_pages: list[int] = []
        empty_pages: list[int] = []
        image_pages: list[int] = []
        suspected_scanned_pages: list[int] = []
        unprocessed_items: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        total_code_blocks = 0

        try:
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                if len(pdf.pages) == 0:
                    raise InvalidDocumentError("PDF contains zero pages.")
                if len(pdf.pages) > self._max_pages:
                    raise InvalidDocumentError(
                        f"PDF exceeds maximum allowed page count ({self._max_pages})."
                    )

                extracted_chars_total = 0
                for page_index, raw_page in enumerate(pdf.pages, start=1):
                    parsed_page = self._parse_page(raw_page, page_number=page_index)
                    extracted_chars_total += len(parsed_page.text)
                    if extracted_chars_total > self._max_extracted_chars:
                        raise InvalidDocumentError(
                            f"PDF extracted text exceeds maximum allowed length "
                            f"({self._max_extracted_chars} characters)."
                        )
                    pages.append(parsed_page)

                    if parsed_page.image_count > 0:
                        image_pages.append(page_index)
                        unprocessed_items.append(
                            f"Sayfa {page_index}: {parsed_page.image_count} gorsel/sekil "
                            "(OCR ve gorsel yorumlama kapsam disi)."
                        )

                    if parsed_page.is_empty:
                        empty_pages.append(page_index)
                    elif parsed_page.suspected_scanned:
                        suspected_scanned_pages.append(page_index)
                        warnings.append(
                            f"Sayfa {page_index} taranmis olabilir (gorsel mevcut, "
                            "cikarilan metin cok az; kesin OCR sonucu degildir)."
                        )

                    if parsed_page.text.strip():
                        text_extracted_pages.append(page_index)

                    total_code_blocks += sum(
                        1
                        for block in parsed_page.blocks
                        if block.kind is BlockKind.CODE
                    )
        except PdfminerException as error:
            inner = error.__context__ or (error.args[0] if error.args else None)
            if isinstance(inner, (PDFPasswordIncorrect, PDFEncryptionError)):
                raise EncryptedDocumentError(
                    "PDF is encrypted or password-protected and cannot be parsed."
                ) from error
            raise InvalidDocumentError(
                f"Failed to parse PDF document: {error}"
            ) from error
        except (PDFPasswordIncorrect, PDFEncryptionError) as error:
            raise EncryptedDocumentError(
                "PDF is encrypted or password-protected and cannot be parsed."
            ) from error
        except (InvalidDocumentError, EncryptedDocumentError):
            raise
        except (
            PDFSyntaxError,
            PSEOF,
            PSSyntaxError,
            ValueError,
            TypeError,
            KeyError,
            OSError,
        ) as error:
            raise InvalidDocumentError(
                f"Failed to parse PDF document: {error}"
            ) from error

        if image_pages and not suspected_scanned_pages:
            warnings.append(
                f"Gorsel iceren sayfalar tespit edildi: {image_pages}. "
                "Gorsellerdeki metin/diyagramlar islenmedi."
            )

        if not text_extracted_pages:
            errors.append("PDF icerisinden hic metin cikarilamadi.")

        report = ExtractionReport(
            total_pages=len(pages),
            text_extracted_pages=tuple(text_extracted_pages),
            empty_pages=tuple(empty_pages),
            image_pages=tuple(image_pages),
            suspected_scanned_pages=tuple(suspected_scanned_pages),
            code_block_count=total_code_blocks,
            unprocessed_items=tuple(unprocessed_items),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

        if not text_extracted_pages:
            raise EmptyDocumentError(
                "No extractable text found in PDF document.",
                report=report,
            )

        return ParsedDocument(
            source_name=resolved_name,
            file_type="application/pdf",
            pages=tuple(pages),
            report=report,
        )

    def _parse_page(self, page: Any, *, page_number: int) -> ParsedPage:
        image_count = len(page.images or ())
        chars: list[dict[str, Any]] = list(page.chars or ())

        if not chars:
            # Fallback to pdfplumber's plain text extractor just in case.
            fallback_text = (page.extract_text() or "").strip()
            is_empty = (not fallback_text) and (image_count == 0)
            suspected_scanned = (image_count > 0) and (
                len(fallback_text) < self._scanned_text_threshold
            )
            blocks = (
                (
                    DocumentBlock(
                        kind=BlockKind.PARAGRAPH,
                        text=fallback_text,
                        page_number=page_number,
                    ),
                )
                if fallback_text
                else ()
            )
            return ParsedPage(
                page_number=page_number,
                text=fallback_text,
                blocks=blocks,
                image_count=image_count,
                is_empty=is_empty,
                suspected_scanned=suspected_scanned,
            )

        page_width = float(page.width or 612.0)
        column_groups = _split_columns_if_two_column(chars, page_width)

        all_blocks: list[DocumentBlock] = []
        body_font_size = _estimate_body_font_size(chars)

        for col_chars in column_groups:
            lines = _reconstruct_lines(
                col_chars,
                y_tolerance=self._line_y_tolerance,
            )
            col_blocks = _group_lines_into_blocks(
                lines,
                page_number=page_number,
                body_font_size=body_font_size,
                heading_size_ratio=self._heading_size_ratio,
            )
            all_blocks.extend(col_blocks)

        page_text = "\n\n".join(block.text for block in all_blocks).strip()
        is_empty = (not page_text) and (image_count == 0)
        suspected_scanned = (image_count > 0) and (
            len(page_text) < self._scanned_text_threshold
        )

        return ParsedPage(
            page_number=page_number,
            text=page_text,
            blocks=tuple(all_blocks),
            image_count=image_count,
            is_empty=is_empty,
            suspected_scanned=suspected_scanned,
        )


def _load_pdf_bytes(
    source: Path | str | bytes,
    source_name: str | None,
) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        if not source:
            raise InvalidDocumentError("PDF byte payload is empty.")
        return source, source_name or "inline.pdf"
    path = Path(source)
    if not path.is_file():
        raise InvalidDocumentError(f"PDF file not found: {path}")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise InvalidDocumentError(f"Unable to read PDF file: {path}") from error
    if not data:
        raise InvalidDocumentError(f"PDF file is empty: {path}")
    return data, source_name or path.name


def _estimate_body_font_size(chars: Sequence[dict[str, Any]]) -> float:
    sizes = [
        float(ch["size"])
        for ch in chars
        if ch.get("text", "").strip() and float(ch.get("size", 0.0)) > 0.0
    ]
    return float(median(sizes)) if sizes else 11.0


def _split_columns_if_two_column(
    chars: Sequence[dict[str, Any]],
    page_width: float,
) -> list[list[dict[str, Any]]]:
    """Detect a clear two-column page and return [left_chars, right_chars].

    Conservative heuristic: only splits when a central vertical gutter has
    almost no non-space characters and both sides contain substantial text.
    """
    visible = [ch for ch in chars if ch.get("text", "").strip()]
    if len(visible) < 20 or page_width <= 0:
        return [list(chars)]

    gutter_left = page_width * 0.46
    gutter_right = page_width * 0.54

    left_chars: list[dict[str, Any]] = []
    right_chars: list[dict[str, Any]] = []
    crossing_count = 0

    for ch in visible:
        x0 = float(ch["x0"])
        x1 = float(ch["x1"])
        if x1 <= gutter_right and x0 < gutter_left:
            left_chars.append(ch)
        elif x0 >= gutter_left and x1 > gutter_right:
            right_chars.append(ch)
        else:
            crossing_count += 1

    if (
        len(left_chars) >= 10
        and len(right_chars) >= 10
        and crossing_count <= max(2, int(len(visible) * 0.02))
    ):
        # Preserve whitespace characters in their respective column side.
        midpoint = page_width * 0.5
        col_left = [ch for ch in chars if float(ch["x0"]) < midpoint]
        col_right = [ch for ch in chars if float(ch["x0"]) >= midpoint]
        return [col_left, col_right]

    return [list(chars)]


def _reconstruct_lines(
    chars: Sequence[dict[str, Any]],
    *,
    y_tolerance: float,
) -> list[_VisualLine]:
    """Group PDF characters into visual lines, preserving internal spacing."""
    if not chars:
        return []

    sorted_chars = sorted(
        chars,
        key=lambda ch: (round(float(ch["top"]) / y_tolerance), float(ch["x0"])),
    )

    raw_rows: list[list[dict[str, Any]]] = []
    for ch in sorted_chars:
        top = float(ch["top"])
        if not raw_rows or abs(top - float(raw_rows[-1][0]["top"])) > y_tolerance:
            raw_rows.append([ch])
        else:
            raw_rows[-1].append(ch)

    visual_lines: list[_VisualLine] = []
    for row in raw_rows:
        row.sort(key=lambda ch: float(ch["x0"]))
        parts: list[str] = []
        prev_x1: float | None = None
        sizes: list[float] = []
        mono_chars = 0
        bold_chars = 0
        visible_chars = 0

        for ch in row:
            text = ch.get("text", "")
            x0 = float(ch["x0"])
            x1 = float(ch["x1"])
            size = float(ch.get("size", 10.0)) or 10.0
            char_width = max(x1 - x0, size * 0.45)

            if prev_x1 is not None:
                gap = x0 - prev_x1
                if gap > char_width * 0.35:
                    # Preserve multi-space gaps inside code/aligned lines.
                    space_count = max(1, int(round(gap / max(size * 0.5, 2.5))))
                    parts.append(" " * min(space_count, 16))
            parts.append(text)
            prev_x1 = max(prev_x1, x1) if prev_x1 is not None else x1

            if text.strip():
                visible_chars += 1
                sizes.append(size)
                fontname = ch.get("fontname")
                if is_monospace_font(fontname):
                    mono_chars += 1
                if is_bold_font(fontname):
                    bold_chars += 1

        joined = "".join(parts).rstrip()
        if not joined.strip():
            continue

        visual_lines.append(
            _VisualLine(
                text=joined,
                top=min(float(ch["top"]) for ch in row),
                bottom=max(float(ch["bottom"]) for ch in row),
                x0=min(float(ch["x0"]) for ch in row),
                x1=max(float(ch["x1"]) for ch in row),
                font_size=float(median(sizes)) if sizes else 10.0,
                is_monospace=(visible_chars > 0 and mono_chars / visible_chars >= 0.6),
                is_bold=(visible_chars > 0 and bold_chars / visible_chars >= 0.7),
            )
        )

    return visual_lines


def _group_lines_into_blocks(
    lines: Sequence[_VisualLine],
    *,
    page_number: int,
    body_font_size: float,
    heading_size_ratio: float,
) -> list[DocumentBlock]:
    if not lines:
        return []

    blocks: list[DocumentBlock] = []
    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]

        # 1. Code block (monospace font or C/Python syntax heuristic)
        if line.is_monospace or looks_like_code_line(line.text):
            code_group: list[_VisualLine] = [line]
            idx += 1
            while idx < total:
                nxt = lines[idx]
                vgap = nxt.top - code_group[-1].bottom
                if vgap > max(code_group[-1].font_size * 2.4, 28.0):
                    break
                if (
                    nxt.is_monospace
                    or looks_like_code_line(nxt.text)
                    or (nxt.x0 >= code_group[0].x0 + 6.0 and not nxt.is_bold)
                ):
                    code_group.append(nxt)
                    idx += 1
                else:
                    break

            code_text = _format_code_group(code_group)
            if code_text.strip():
                blocks.append(
                    DocumentBlock(
                        kind=BlockKind.CODE,
                        text=code_text,
                        page_number=page_number,
                        language_hint=infer_code_language(code_text),
                    )
                )
            continue

        # 2. Heading (larger font, bold short line, or numbered heading)
        is_large = line.font_size >= body_font_size * heading_size_ratio
        is_short_bold = (
            line.is_bold
            and len(line.text.strip()) <= 120
            and not line.text.strip().endswith((".", ";", ","))
        )
        if is_large or is_short_bold or looks_like_heading_text(line.text):
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.HEADING,
                    text=line.text.strip(),
                    page_number=page_number,
                )
            )
            idx += 1
            continue

        # 3. Paragraph
        para_group: list[_VisualLine] = [line]
        idx += 1
        while idx < total:
            nxt = lines[idx]
            if nxt.is_monospace or looks_like_code_line(nxt.text):
                break
            if nxt.font_size >= body_font_size * heading_size_ratio:
                break
            if (
                nxt.is_bold
                and len(nxt.text.strip()) <= 120
                and not nxt.text.strip().endswith((".", ";", ","))
            ):
                break
            vgap = nxt.top - para_group[-1].bottom
            if vgap > max(para_group[-1].font_size * 0.9, 10.0):
                break
            para_group.append(nxt)
            idx += 1

        para_text = "\n".join(item.text.strip() for item in para_group)
        if para_text.strip():
            blocks.append(
                DocumentBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=para_text,
                    page_number=page_number,
                )
            )

    return blocks


def _format_code_group(code_lines: Sequence[_VisualLine]) -> str:
    """Reconstruct relative leading indentation for a group of code lines."""
    base_x0 = min(line.x0 for line in code_lines)
    avg_font = float(median([line.font_size for line in code_lines])) or 10.0
    # Monospace character width is roughly 0.6 * font_size.
    space_unit = max(avg_font * 0.6, 4.0)

    formatted: list[str] = []
    for i, line in enumerate(code_lines):
        if i > 0:
            vgap = line.top - code_lines[i - 1].bottom
            if vgap > max(line.font_size * 0.95, 11.0):
                formatted.append("")
        delta_x = max(0.0, line.x0 - base_x0)
        indent_spaces = int(round(delta_x / space_unit))
        formatted.append((" " * indent_spaces) + line.text.lstrip())

    return "\n".join(formatted).strip("\n")
