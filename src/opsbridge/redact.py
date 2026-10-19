"""PII / secret redaction applied to everything written to audit logs and traces (and before any text is sent to an LLM)."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d")),
    ("SECRET", re.compile(r"(?i)\b(?:password|secret|token|api[_-]?key)\b\s*[:=]\s*\S+")),
]


def redact_text(text: str) -> str:
    for label, rx in _PATTERNS:
        text = rx.sub(f"[{label}]", text)
    return text


def redact(obj: Any) -> Any:
    """Recursively redact strings inside dicts/lists/tuples."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj
