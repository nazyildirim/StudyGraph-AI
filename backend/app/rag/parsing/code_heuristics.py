"""Heuristic helpers for code-block, language, and heading detection.

All heuristics here are best-effort and intentionally conservative: PDF and
plain-text layout cannot be classified with 100% certainty across every file.
"""

from __future__ import annotations

import re

_MONOSPACE_FONT_TOKENS: tuple[str, ...] = (
    "courier",
    "consolas",
    "mono",
    "menlo",
    "monaco",
    "fixed",
    "inconsolata",
    "firacode",
    "sourcecode",
    "hack",
    "typewriter",
    "cmtt",
)

_C_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*#\s*(include|define|ifdef|ifndef|endif)\b"),
    re.compile(r"\b(printf|scanf|malloc|calloc|free|sizeof)\s*\("),
    re.compile(r"^\s*(int|void|char|float|double|struct|typedef|const)\s+\*?\w+"),
    re.compile(r"->|\*\w+\s*=|&\w+"),
    re.compile(r"^\s*(for|while|if|switch)\s*\(.*\)\s*\{?\s*$"),
    re.compile(r"^\s*[\{\}]\s*;?\s*$"),
)

_PYTHON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(def|class)\s+\w+\s*[\(:]"),
    re.compile(r"^\s*(from\s+[\w.]+\s+import|import\s+[\w.]+)\b"),
    re.compile(r"^\s*(if|elif|else|for|while|try|except|finally|with)\b.*:\s*$"),
    re.compile(r"^\s*return\b"),
    re.compile(r"\bprint\s*\("),
    re.compile(r"^\s*@\w+"),
)

_NUMBERED_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+\S")


def is_monospace_font(fontname: str | None) -> bool:
    """Return True if a PDF font name indicates a monospace typeface."""
    if not fontname:
        return False
    lowered = fontname.lower()
    return any(token in lowered for token in _MONOSPACE_FONT_TOKENS)


def is_bold_font(fontname: str | None) -> bool:
    """Return True if a PDF font name indicates a bold typeface."""
    if not fontname:
        return False
    lowered = fontname.lower()
    return "bold" in lowered or "black" in lowered or "semibold" in lowered


def looks_like_code_line(line: str) -> bool:
    """Heuristically check whether a single line looks like C or Python code."""
    stripped = line.strip()
    if not stripped:
        return False
    if any(pattern.search(line) for pattern in _C_PATTERNS):
        return True
    if any(pattern.search(line) for pattern in _PYTHON_PATTERNS):
        return True
    if stripped.endswith(";") and any(ch in stripped for ch in ("=", "(", ")", "*", "[")):
        return True
    return False


def infer_code_language(code_text: str) -> str | None:
    """Best-effort language hint ('c', 'python', or None) for a code block."""
    c_hits = sum(
        1
        for line in code_text.splitlines()
        if any(pattern.search(line) for pattern in _C_PATTERNS)
    )
    py_hits = sum(
        1
        for line in code_text.splitlines()
        if any(pattern.search(line) for pattern in _PYTHON_PATTERNS)
    )
    if c_hits > py_hits and c_hits > 0:
        return "c"
    if py_hits > c_hits and py_hits > 0:
        return "python"
    return None


def looks_like_heading_text(text: str) -> bool:
    """Check whether short non-code text matches a section heading pattern."""
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    if stripped.endswith((".", ";", ",", ":")):
        return False
    if stripped.startswith("#"):
        return True
    if _NUMBERED_HEADING_RE.match(stripped) and len(stripped.split()) <= 12:
        return True
    return False
