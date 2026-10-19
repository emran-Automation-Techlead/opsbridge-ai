"""PII / secret redaction applied to everything written to audit logs and traces (and before any text is sent to an LLM).

Bug history: the first phone pattern also matched ISO dates/timestamps ("2026-10-19T22:58:47"), turning every audit `ts` into "[PHONE]".
Found in the real DynamoDB console during the AWS demo. Fixed by (1) checking the digit count and excluding date-like text and
(2) never redacting identifier/timestamp fields (ts, trace_id, ids). Names are still not redacted (documented limitation).
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PHONE = re.compile(r"(?<![\w:.-])\+?\d[\d ()-]{8,}\d(?![\w:])")
_SECRET = re.compile(r"(?i)\b(?:password|secret|token|api[_-]?key)\b\s*[:=]\s*\S+")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}[-/]\d{2}[-/]\d{4}$")

# fields that hold identifiers or timestamps: never redacted
SAFE_KEYS = {"ts", "trace_id", "id", "approval_id", "requested_at", "decided_at", "timestamp", "completed_at", "deletion_timestamp"}


def _phone(m: re.Match) -> str:
    text = m.group(0).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) < 10 or _DATE_LIKE.match(text):
        return m.group(0)
    return "[PHONE]"


def redact_text(text: str) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _AWS_KEY.sub("[AWS_KEY]", text)
    text = _SSN.sub("[SSN]", text)
    text = _CARD.sub("[CARD]", text)
    text = _PHONE.sub(_phone, text)
    return _SECRET.sub("[SECRET]", text)


def redact(obj: Any) -> Any:
    """Recursively redact strings inside dicts/lists/tuples, leaving identifier and timestamp fields intact."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: (v if k in SAFE_KEYS and isinstance(v, str) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj
