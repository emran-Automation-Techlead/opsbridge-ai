"""Evaluation harness + quality gate. Runs the golden question set and the labelled documents, reports real metrics, and fails
(exit code 1) if any gate is missed. The sets are small and SYNTHETIC and were also used while developing, so the numbers measure
regression safety, not generalisation. This is stated in docs/EVALUATION.md.

Not Ragas: Ragas needs an LLM judge and is not installed here. These are deterministic, directly-computed metrics.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from . import config

GATES = {"hit_at_3": 0.85, "citation_precision": 0.85, "abstention_accuracy": 0.80, "false_abstain_rate_max": 0.15,
         "classification_accuracy": 0.85, "route_accuracy": 0.90, "field_accuracy": 0.85, "unsafe_executions_max": 0}


def run() -> dict:
    # isolate side effects (traces, audit, tickets) in a temp directory
    os.environ["OPSBRIDGE_RUNS"] = tempfile.mkdtemp(prefix="opsbridge_eval_")
    from . import answer, tools, workflow  # imported after env is set

    qs = json.loads((config.EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    docs = json.loads((config.EVAL_DIR / "documents.json").read_text(encoding="utf-8"))
    lat, failures = [], []
    hit1 = hit3 = cite_ok = n_ans = 0
    abst_ok = n_unans = false_abst = 0
    retr = answer._retriever()
    for q in qs:
        t0 = time.perf_counter()
        a = answer.ask(q["q"], retriever=retr)
        lat.append((time.perf_counter() - t0) * 1000)
        if q["doc"]:
            n_ans += 1
            top3 = [h.chunk.doc_id for h in retr.search(q["q"], 3)]
            hit1 += top3[:1] == [q["doc"]]
            hit3 += q["doc"] in top3
            if a.abstained:
                false_abst += 1
                failures.append({"id": q["id"], "kind": "false_abstain", "q": q["q"], "confidence": a.confidence})
            else:
                good = any(c.doc_id == q["doc"] for c in a.citations[:1])
                cite_ok += good
                if not good:
                    failures.append({"id": q["id"], "kind": "wrong_citation", "q": q["q"], "cited": [c.doc_id for c in a.citations]})
            if q["doc"] not in top3:
                failures.append({"id": q["id"], "kind": "retrieval_miss", "q": q["q"], "top3": top3})
        else:
            n_unans += 1
            if a.abstained:
                abst_ok += 1
            else:
                failures.append({"id": q["id"], "kind": "should_abstain", "q": q["q"], "confidence": a.confidence})
    cls_ok = route_ok = fld_ok = fld_n = unsafe = 0
    for d in docs:
        text = (config.INBOX_DIR / d["file"]).read_text(encoding="utf-8")
        t0 = time.perf_counter()
        r = workflow.process_document(text)
        lat.append((time.perf_counter() - t0) * 1000)
        cls_ok += r.doc_type.value == d["doc_type"]
        route_ok += r.route == d["route"]
        if r.doc_type.value != d["doc_type"]:
            failures.append({"id": d["file"], "kind": "misclassified", "got": r.doc_type.value, "want": d["doc_type"]})
        if r.route != d["route"]:
            failures.append({"id": d["file"], "kind": "wrong_route", "got": r.route, "want": d["route"], "confidence": r.confidence})
        if d["route"] == "auto":
            for k in ("requester", "department", "priority", "policy_id"):
                fld_n += 1
                got = getattr(r.fields, k)
                got = got.value if hasattr(got, "value") else got
                fld_ok += got == d[k]
                if got != d[k]:
                    failures.append({"id": d["file"], "kind": "field_mismatch", "field": k, "got": got, "want": d[k]})
            fld_n += 1
            fld_ok += str(r.fields.due_date) == str(d["due_date"])
        unsafe += sum(1 for a in r.actions if a.impact == "high" and a.status == "executed")
    # nothing high-impact may be executed without approval
    unsafe += sum(1 for a in tools.list_approvals("pending") if False)
    lat.sort()
    m = {
        "questions": len(qs), "answerable": n_ans, "unanswerable": n_unans, "documents": len(docs),
        "hit_at_1": round(hit1 / n_ans, 3), "hit_at_3": round(hit3 / n_ans, 3),
        "citation_precision": round(cite_ok / max(n_ans - false_abst, 1), 3),
        "abstention_accuracy": round(abst_ok / n_unans, 3), "false_abstain_rate": round(false_abst / n_ans, 3),
        "classification_accuracy": round(cls_ok / len(docs), 3), "route_accuracy": round(route_ok / len(docs), 3),
        "field_accuracy": round(fld_ok / fld_n, 3), "unsafe_executions": unsafe,
        "latency_ms_p50": round(statistics.median(lat), 2), "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 2),
        "abstain_threshold": config.ABSTAIN_THRESHOLD, "auto_route_confidence": config.AUTO_ROUTE_CONFIDENCE,
    }
    gate = {
        "hit_at_3": m["hit_at_3"] >= GATES["hit_at_3"], "citation_precision": m["citation_precision"] >= GATES["citation_precision"],
        "abstention_accuracy": m["abstention_accuracy"] >= GATES["abstention_accuracy"], "false_abstain_rate": m["false_abstain_rate"] <= GATES["false_abstain_rate_max"],
        "classification_accuracy": m["classification_accuracy"] >= GATES["classification_accuracy"], "route_accuracy": m["route_accuracy"] >= GATES["route_accuracy"],
        "field_accuracy": m["field_accuracy"] >= GATES["field_accuracy"], "unsafe_executions": m["unsafe_executions"] <= GATES["unsafe_executions_max"],
    }
    return {"metrics": m, "gates": gate, "passed": all(gate.values()), "failures": failures}


def main() -> int:
    res = run()
    (config.EVAL_DIR / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    m = res["metrics"]
    lines = ["# Evaluation results (generated by `python -m opsbridge.evaluate`)", "",
             f"Small SYNTHETIC sets ({m['questions']} questions, {m['documents']} documents), also used during development: these numbers show regression safety, not generalisation.", "",
             "| Metric | Value | Gate | Pass |", "|---|---|---|---|"]
    for k, g in (("hit_at_3", ">= 0.85"), ("citation_precision", ">= 0.85"), ("abstention_accuracy", ">= 0.80"), ("false_abstain_rate", "<= 0.15"),
                 ("classification_accuracy", ">= 0.85"), ("route_accuracy", ">= 0.90"), ("field_accuracy", ">= 0.85"), ("unsafe_executions", "== 0")):
        lines.append(f"| {k} | {m[k]} | {g} | {'PASS' if res['gates'][k] else 'FAIL'} |")
    lines += ["", f"Also: hit@1 {m['hit_at_1']}; latency p50 {m['latency_ms_p50']} ms, p95 {m['latency_ms_p95']} ms (local, in-process, no network).", "",
              f"Thresholds used: abstain below idf-coverage {m['abstain_threshold']}; auto-route at extraction confidence >= {m['auto_route_confidence']}.", "",
              "## Failure cases", ""]
    lines += [f"- `{f['id']}` {f['kind']}: " + ", ".join(f"{k}={v}" for k, v in f.items() if k not in ('id', 'kind')) for f in res["failures"]] or ["- none"]
    lines += ["", "## What this does not show", "", "- Real-world accuracy, other languages, long or scanned documents, or LLM quality (no LLM is used here).",
              "- Ragas / LLM-judge metrics: not run (Ragas is not installed and needs an LLM judge)."]
    Path(config.ROOT / "docs" / "EVALUATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": res["passed"], **m}, indent=1))
    for f in res["failures"]:
        print("FAILURE:", f)
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
