"""Append-only audit log. Every event is redacted before it is written and carries the trace id."""
from __future__ import annotations

from datetime import datetime, timezone

from . import store
from .redact import redact


def write(trace_id: str, actor: str, action: str, outcome: str, **details) -> dict:
    event = redact({
        "ts": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "actor": actor,
        "action": action,
        "outcome": outcome,
        "details": details,
    })
    store.get_store().append("audit", event)
    return event


def read_all() -> list[dict]:
    return store.get_store().read("audit")
