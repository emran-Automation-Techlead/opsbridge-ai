import json
from pathlib import Path

import pytest

from opsbridge import answer, audit, classify, config, tools, workflow
from opsbridge.models import DocType, ToolCall
from opsbridge.retrieval import Retriever

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
QS = json.loads((ROOT / "data" / "eval" / "questions.json").read_text(encoding="utf-8"))


def doc(name): return (INBOX / f"{name}.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------- SPEC-001 / 002
@pytest.mark.spec("SPEC-001")
def test_answer_is_grounded_and_cited():
    a = answer.ask("How long is published content kept before it is archived?")
    assert not a.abstained and a.citations
    assert a.citations[0].doc_id == "POL-001" and "24 months" in a.answer


@pytest.mark.spec("SPEC-001")
@pytest.mark.parametrize("q", [x for x in QS if x["doc"]], ids=lambda x: x["id"])
def test_every_answerable_golden_question_cites_the_right_policy(q):
    a = answer.ask(q["q"])
    assert not a.abstained, f"false abstain (confidence {a.confidence})"
    assert a.citations[0].doc_id == q["doc"]


@pytest.mark.spec("SPEC-002")
@pytest.mark.parametrize("q", [x for x in QS if not x["doc"]], ids=lambda x: x["id"])
def test_out_of_scope_questions_abstain(q):
    a = answer.ask(q["q"])
    assert a.abstained and not a.citations and "enough evidence" in a.answer


@pytest.mark.spec("SPEC-002")
def test_abstention_is_audited():
    answer.ask("What is the dress code in the office?")
    assert any(e["action"] == "ask" and e["outcome"] == "abstained" for e in audit.read_all())


def test_retriever_is_deterministic():
    r = Retriever()
    a = [h.chunk.chunk_id for h in r.search("legal hold retention")]
    assert a == [h.chunk.chunk_id for h in r.search("legal hold retention")] and a[0].startswith("POL-001")


# ---------------------------------------------------------------- SPEC-003
@pytest.mark.spec("SPEC-003")
def test_classification_and_extraction():
    r = workflow.process_document(doc("D01"))
    assert r.doc_type == DocType.policy_change_request and r.route == "auto"
    assert r.fields.requester == "Priya Nair" and r.fields.department == "Policy Operations"
    assert r.fields.priority.value == "high" and str(r.fields.due_date) == "2026-11-20" and r.fields.policy_id == "POL-003"


@pytest.mark.spec("SPEC-003")
def test_low_confidence_goes_to_review_and_runs_no_tools():
    r = workflow.process_document(doc("D09"))
    assert r.route == "review" and r.actions == [] and r.confidence < config.AUTO_ROUTE_CONFIDENCE
    assert (config.runs_dir() / "review_queue.jsonl").exists()
    assert not (config.runs_dir() / "tickets.jsonl").exists()


@pytest.mark.spec("SPEC-003")
def test_instruction_like_text_is_flagged_and_sent_to_review():
    r = workflow.process_document(doc("D10"))
    assert classify.is_suspicious(doc("D10")) and r.route == "review" and r.actions == []
    assert not (config.runs_dir() / "register.jsonl").exists()


@pytest.mark.spec("SPEC-003")
def test_bad_due_date_does_not_crash():
    f = classify.extract("From: A B (X)\nSubject: S\nPriority: Low\nDue: not-a-date\n\nbody")
    assert f.due_date is None


# ---------------------------------------------------------------- SPEC-004
@pytest.mark.spec("SPEC-004")
def test_unknown_tool_is_refused():
    r = tools.dispatch(ToolCall(tool="delete_everything", args={}), "t1")
    assert r.status == "not_allowed"


@pytest.mark.spec("SPEC-004")
def test_invalid_arguments_are_refused():
    r = tools.dispatch(ToolCall(tool="create_ticket", args={"ticket_type": "access_request", "summary": "x", "priority": "urgent!", "owner_team": "it"}), "t1")
    assert r.status == "invalid"
    r2 = tools.dispatch(ToolCall(tool="update_policy_register", args={"policy_id": "BAD", "change_summary": "x" * 10}), "t1")
    assert r2.status == "invalid"


@pytest.mark.spec("SPEC-004")
def test_low_impact_tool_executes():
    r = tools.dispatch(ToolCall(tool="notify_owner", args={"team": "security", "message": "Please review"}), "t1")
    assert r.status == "executed" and (config.runs_dir() / "notifications.jsonl").exists()


# ---------------------------------------------------------------- SPEC-005
HIGH = ToolCall(tool="update_policy_register", args={"policy_id": "POL-003", "change_summary": "Reorder review step"})


@pytest.mark.spec("SPEC-005")
def test_high_impact_waits_for_approval():
    r = tools.dispatch(HIGH, "t1")
    assert r.status == "pending_approval" and r.approval_id
    assert not (config.runs_dir() / "register.jsonl").exists()


@pytest.mark.spec("SPEC-005")
def test_workflow_cannot_self_approve_and_decision_is_single_use():
    aid = tools.dispatch(HIGH, "t1").approval_id
    with pytest.raises(PermissionError):
        tools.decide(aid, "workflow", True)
    done = tools.decide(aid, "Dana Wu", True)
    assert done["status"] == "approved" and (config.runs_dir() / "register.jsonl").exists()
    with pytest.raises(ValueError):
        tools.decide(aid, "Dana Wu", False)


@pytest.mark.spec("SPEC-005")
def test_rejected_action_never_runs():
    aid = tools.dispatch(HIGH, "t1").approval_id
    assert tools.decide(aid, "Dana Wu", False)["status"] == "rejected"
    assert not (config.runs_dir() / "register.jsonl").exists()


@pytest.mark.spec("SPEC-005")
def test_takedown_document_creates_ticket_and_pending_legal_escalation():
    r = workflow.process_document(doc("D02"))
    status = {a.tool: a.status for a in r.actions}
    assert status == {"create_ticket": "executed", "escalate_to_legal": "pending_approval"}
    assert not (config.runs_dir() / "legal.jsonl").exists()


# ---------------------------------------------------------------- SPEC-006 / 007
@pytest.mark.spec("SPEC-006")
def test_personal_data_never_reaches_logs():
    workflow.process_document(doc("D11"))
    blob = "".join(p.read_text(encoding="utf-8") for p in config.runs_dir().glob("*.jsonl"))
    assert "jane.roe@example.com" not in blob and "98765" not in blob
    assert "[EMAIL]" in blob or "[PHONE]" in blob or "Jane Roe" in blob  # redaction ran; names are not treated as secrets


@pytest.mark.spec("SPEC-006")
def test_every_audit_event_has_a_trace_id():
    answer.ask("How long are audit logs retained?")
    workflow.process_document(doc("D04"))
    events = audit.read_all()
    assert events and all(e["trace_id"] for e in events)


@pytest.mark.spec("SPEC-006")
def test_redactor_covers_secrets_and_cards():
    from opsbridge.redact import redact_text
    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at runtime so no key-shaped string sits in the source
    s = redact_text(f"key {fake_key} card 4111 1111 1111 1111 ssn 123-45-6789 password: hunter2")
    assert "AKIA" not in s and "4111" not in s and "123-45" not in s and "hunter2" not in s


@pytest.mark.spec("SPEC-007")
def test_trace_has_unique_id_and_spans():
    a = answer.ask("How many editors review content before publication?")
    b = answer.ask("How many editors review content before publication?")
    lines = [json.loads(x) for x in (config.runs_dir() / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert a.trace_id != b.trace_id and len(lines) == 2
    assert {s["span"] for s in lines[0]["spans"]} >= {"retrieve", "compose"} and all("duration_ms" in s for s in lines[0]["spans"])


@pytest.mark.spec("SPEC-006")
def test_timestamps_and_ids_survive_redaction_but_phones_do_not():
    from opsbridge.redact import redact, redact_text
    ev = redact({"ts": "2026-10-19T22:58:47.123456+00:00", "trace_id": "4670dc72072e5a1b9c3d8e7f6a5b4c3d", "details": {"note": "call +91 98765 43210 or (555) 123-4567 on 2026-10-19"}})
    assert ev["ts"] == "2026-10-19T22:58:47.123456+00:00" and ev["trace_id"] == "4670dc72072e5a1b9c3d8e7f6a5b4c3d"
    assert "98765" not in ev["details"]["note"] and "123-4567" not in ev["details"]["note"] and "2026-10-19" in ev["details"]["note"]
    assert redact_text("due 2026-11-20 at 10:30:00") == "due 2026-11-20 at 10:30:00"
    assert redact_text("order 12345") == "order 12345"


@pytest.mark.spec("SPEC-006")
def test_stored_audit_events_keep_a_real_timestamp():
    from datetime import datetime
    answer.ask("How long are audit logs retained?")
    events = audit.read_all()
    assert events and all(datetime.fromisoformat(e["ts"]) for e in events)
