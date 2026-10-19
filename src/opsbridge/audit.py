"""Append-only audit log. Every event is redacted before it is written and carries the trace id."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config
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
    with (config.runs_dir() / "audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    return event


def read_all() -> list[dict]:
    p = config.runs_dir() / "audit.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
