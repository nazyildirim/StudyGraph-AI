"""Pytest compatibility tests for the legacy `backend/rag/text_splitter.py` wrapper."""

from __future__ import annotations

import pytest

from rag.text_splitter import split_text


def test_legacy_split_text_rejects_non_positive_chunk_size() -> None:
    with pytest.raises(ValueError):
        split_text("ornek metin", 0)
    with pytest.raises(ValueError):
        split_text("ornek metin", -5)


def test_legacy_split_text_splits_and_preserves_printf_code() -> None:
    sample = (
        "C dilinde pointer kullanimi.\n\n"
        "#include <stdio.h>\n"
        "int main(void) {\n"
        "    int x = 10;\n"
        "    int *p = &x;\n"
        '    printf("%d\\n", *p);\n'
        "    return 0;\n"
        "}\n"
    )
    chunks = split_text(sample, 120)
    assert len(chunks) >= 1
    assert any("printf" in chunk for chunk in chunks)
    assert split_text("   ", 100) == []
