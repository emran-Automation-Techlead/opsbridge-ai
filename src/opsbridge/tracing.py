"""Minimal OpenTelemetry-style tracing: one trace id per request, named spans with durations, written as JSON lines.
This is a deliberately small local implementation. It is NOT Langfuse/Arize; the span fields are chosen so an exporter can be added."""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager

from . import config
from .redact import redact


class Trace:
    def __init__(self, name: str):
        self.trace_id = uuid.uuid4().hex
        self.name = name
        self.spans: list[dict] = []
        self._t0 = time.perf_counter()

    @contextmanager
    def span(self, name: str, **attrs):
        start = time.perf_counter()
        record = {"trace_id": self.trace_id, "span": name, "attrs": redact(attrs), "status": "ok"}
        try:
            yield record
        except Exception as exc:  # record then re-raise
            record["status"] = "error"
            record["error"] = type(exc).__name__
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
            self.spans.append(record)

    def finish(self) -> float:
        total = round((time.perf_counter() - self._t0) * 1000, 3)
        path = config.runs_dir() / "trace.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"trace_id": self.trace_id, "name": self.name, "total_ms": total, "spans": self.spans}) + "\n")
        return total
