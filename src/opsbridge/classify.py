"""Document understanding: classification plus structured extraction with validation and a confidence score.

Rule-based by design (deterministic, testable, free). An LLM extractor can replace extract() behind the same ExtractedRequest schema.
Documents are DATA: nothing inside a document is ever executed or obeyed. Suspicious instruction-like text is flagged for human review.
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

from .models import DocType, ExtractedRequest, Priority

KEYWORDS: dict[DocType, list[str]] = {
    DocType.policy_change_request: ["policy", "pol-", "change", "amend", "update", "effective", "revise"],
    DocType.content_takedown_request: ["takedown", "take down", "remove", "copyright", "defamation", "dmca", "court order", "notice"],
    DocType.vendor_onboarding_request: ["vendor", "supplier", "onboard", "security questionnaire", "data processing", "procurement"],
    DocType.access_request: ["access", "permission", "privileged", "account", "repository", "login"],
    DocType.exception_request: ["exception", "waiver", "exemption", "deviation"],
}
INJECTION = re.compile(r"(?i)\b(ignore (all |your |previous )?(rules|instructions)|system:|disregard|without (waiting for )?approval|you are now)\b")
_HEADER = re.compile(r"^(From|Subject|Priority|Due):\s*(.+)$", re.MULTILINE)


def parse_headers(text: str) -> tuple[dict[str, str], str]:
    headers = {m.group(1).lower(): m.group(2).strip() for m in _HEADER.finditer(text)}
    body = _HEADER.sub("", text).strip()
    return headers, body


def classify(text: str) -> tuple[DocType, float, float]:
    """Return (type, top score, margin). Subject words count double."""
    headers, body = parse_headers(text)
    subject = headers.get("subject", "").lower()
    low = body.lower()
    scores = {}
    for dt, kws in KEYWORDS.items():
        scores[dt] = sum(low.count(k) + 2 * subject.count(k) for k in kws)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 == 0:
        return DocType.unknown, 0.0, 0.0
    return best, float(s1), round((s1 - s2) / s1, 3)


def extract(text: str) -> ExtractedRequest:
    headers, _ = parse_headers(text)
    requester, department = None, None
    if "from" in headers:
        m = re.match(r"^(.*?)\s*(?:\((.*?)\))?$", headers["from"])
        requester, department = (m.group(1) or None), (m.group(2) if m else None)
    explicit = headers.get("priority", "").lower()
    if explicit in {"low", "medium", "high"}:
        priority = Priority(explicit)
    elif re.search(r"(?i)\b(urgent|asap|immediately)\b", text):
        priority = Priority.high
    else:
        priority = Priority.medium
    due = None
    if "due" in headers:
        try:
            due = date.fromisoformat(headers["due"])
        except ValueError:
            due = None
    m = re.search(r"\bPOL-\d{3}\b", text)
    return ExtractedRequest(requester=requester, department=department, subject=headers.get("subject"),
                            priority=priority, due_date=due, policy_id=m.group(0) if m else None)


def confidence(doc_type: DocType, margin: float, fields: ExtractedRequest, text: str) -> float:
    """Share of four checks that pass: requester found, subject found, priority known (explicit or inferred), classification clear."""
    headers, _ = parse_headers(text)
    checks = [
        bool(fields.requester),
        bool(fields.subject),
        "priority" in headers or bool(re.search(r"(?i)\b(urgent|asap|immediately)\b", text)),
        doc_type != DocType.unknown and margin >= 0.2,
    ]
    return sum(checks) / len(checks)


def is_suspicious(text: str) -> bool:
    return bool(INJECTION.search(text))


def validate(fields: dict) -> ExtractedRequest | None:
    try:
        return ExtractedRequest(**fields)
    except ValidationError:
        return None
