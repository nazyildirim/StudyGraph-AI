"""Zero-dependency pure-Python PDF 1.4 fixture generator for tests.

Generates small, deterministic, valid PDF files supporting:
- Multiple pages
- Helvetica (prose), Helvetica-Bold (headings), Courier (monospace code)
- Turkish Unicode characters via a custom /ToUnicode CMap
- Embedded XObject images (detected by pdfplumber's `page.images`)
- Empty pages, scanned-like pages (image with no text), two-column pages
- Encrypted and corrupt PDF payloads
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Custom byte slots mapped via /ToUnicode CMap so pdfminer extracts Turkish
# Unicode cleanly using standard Type1 fonts with zero external dependencies.
_TURKISH_MAP: dict[str, int] = {
    "ç": 0x80,
    "ğ": 0x81,
    "ı": 0x82,
    "İ": 0x83,
    "ö": 0x84,
    "ş": 0x85,
    "ü": 0x86,
    "Ç": 0x87,
    "Ğ": 0x88,
    "Ö": 0x89,
    "Ş": 0x8A,
    "Ü": 0x8B,
}

_FONT_MAP: dict[str, str] = {
    "body": "F1",
    "bold": "F2",
    "code": "F3",
}


@dataclass(frozen=True)
class TextItem:
    """A single line of text placed at (x, y) in PDF points (origin bottom-left)."""

    text: str
    x: float
    y: float
    size: float = 11.0
    font: str = "body"  # "body" | "bold" | "code"


@dataclass(frozen=True)
class PageSpec:
    """Specification for a single synthetic PDF page."""

    items: tuple[TextItem, ...] = ()
    image_count: int = 0
    width: float = 612.0
    height: float = 792.0


def _encode_pdf_hex(text: str) -> str:
    """Encode text as a PDF hex string using ASCII + Turkish CMap byte codes."""
    out = bytearray()
    for ch in text:
        if ch in _TURKISH_MAP:
            out.append(_TURKISH_MAP[ch])
        else:
            code = ord(ch)
            if code > 0x7F:
                raise ValueError(f"Unsupported non-ASCII test char: {ch!r}")
            out.append(code)
    return "<" + out.hex().upper() + ">"


def _build_tounicode_cmap() -> bytes:
    entries = []
    # Map standard printable ASCII 0x20..0x7E
    for code in range(0x20, 0x7F):
        entries.append(f"<{code:02X}> <{code:04X}>")
    # Map Turkish characters
    for ch, byte_val in _TURKISH_MAP.items():
        entries.append(f"<{byte_val:02X}> <{ord(ch):04X}>")

    # PDF CMap allows at most 100 entries per beginbfchar block.
    blocks: list[str] = []
    for i in range(0, len(entries), 100):
        chunk = entries[i : i + 100]
        blocks.append(f"{len(chunk)} beginbfchar\n" + "\n".join(chunk) + "\nendbfchar")

    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /StudyGraphTest def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n"
        "<00> <FF>\n"
        "endcodespacerange\n"
        + "\n".join(blocks)
        + "\nendcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end\n"
        "end\n"
    )
    return cmap.encode("ascii")


def build_pdf(
    pages: Sequence[PageSpec],
    *,
    encrypted: bool = False,
) -> bytes:
    """Build a valid PDF 1.4 byte payload from the given page specifications."""
    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based PDF object number

    # Object 1: Catalog (placeholder, updated once Pages id is known)
    catalog_id = add_obj(b"")
    # Object 2: Pages (placeholder)
    pages_id = add_obj(b"")

    # Object 3: ToUnicode CMap stream
    cmap_bytes = _build_tounicode_cmap()
    cmap_id = add_obj(
        f"<< /Length {len(cmap_bytes)} >>\nstream\n".encode("ascii")
        + cmap_bytes
        + b"endstream"
    )

    # Objects 4, 5, 6: Fonts (Helvetica, Helvetica-Bold, Courier)
    f1_id = add_obj(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode {cmap_id} 0 R >>".encode(
            "ascii"
        )
    )
    f2_id = add_obj(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /ToUnicode {cmap_id} 0 R >>".encode(
            "ascii"
        )
    )
    f3_id = add_obj(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /ToUnicode {cmap_id} 0 R >>".encode(
            "ascii"
        )
    )

    # Object 7: 1x1 RGB Image XObject
    img_data = b"\xff\x00\x00"
    img_id = add_obj(
        (
            f"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length {len(img_data)} >>\n"
            f"stream\n"
        ).encode("ascii")
        + img_data
        + b"\nendstream"
    )

    page_ids: list[int] = []
    for spec in pages:
        cmds: list[str] = []
        for item in spec.items:
            font_key = _FONT_MAP[item.font]
            hex_text = _encode_pdf_hex(item.text)
            cmds.append(
                f"BT /{font_key} {item.size:.2f} Tf 1 0 0 1 {item.x:.2f} {item.y:.2f} Tm {hex_text} Tj ET"
            )
        for img_idx in range(spec.image_count):
            y_pos = 500 - img_idx * 120
            cmds.append(f"q 100 0 0 100 72 {y_pos} cm /Im1 Do Q")

        stream_bytes = ("\n".join(cmds) + "\n").encode("ascii")
        content_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"endstream"
        )

        xobj_part = f"/XObject << /Im1 {img_id} 0 R >>" if spec.image_count > 0 else ""
        page_dict = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 {spec.width:.0f} {spec.height:.0f}] "
            f"/Resources << /Font << /F1 {f1_id} 0 R /F2 {f2_id} 0 R /F3 {f3_id} 0 R >> "
            f"{xobj_part} >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        page_ids.append(add_obj(page_dict))

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("ascii")
    )
    objects[catalog_id - 1] = (
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    )

    encrypt_ref = ""
    if encrypted:
        enc_id = add_obj(
            b"<< /Filter /Standard /V 1 /R 2 "
            b"/O <0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF> "
            b"/U <0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF> "
            b"/P -4 >>"
        )
        encrypt_ref = f"/Encrypt {enc_id} 0 R /ID [<AABBCCDD> <AABBCCDD>] "

    # Serialize PDF with valid xref table.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R "
            f"{encrypt_ref}>>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)
