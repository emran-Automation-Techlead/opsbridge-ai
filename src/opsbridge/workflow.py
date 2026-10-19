"""End-to-end document workflow: classify -> extract -> validate -> route -> propose tool calls -> gate -> audit."""
from __future__ import annotations

from . import audit, classify, config, store, tools
from .models import ActionResult, DocType, ProcessResult, ToolCall
from .tracing import Trace

OWNER = {
    DocType.policy_change_request: "policy-ops", DocType.content_takedown_request: "legal-ops",
    DocType.vendor_onboarding_request: "procurement", DocType.access_request: "it", DocType.exception_request: "policy-ops",
}


def plan_actions(doc_type: DocType, fields) -> list[ToolCall]:
    """Deterministic planner. Document text can never add or change tools: only type and extracted fields feed this table."""
    summary = (fields.subject or doc_type.value)[:190]
    owner = OWNER.get(doc_type, "policy-ops")
    calls = [ToolCall(tool="create_ticket", args={"ticket_type": doc_type.value, "summary": summary, "priority": fields.priority.value, "owner_team": owner})]
    if doc_type == DocType.policy_change_request:
        calls.append(ToolCall(tool="notify_owner", args={"team": "policy-ops", "message": f"New policy change request: {summary}"}))
        if fields.policy_id:
            calls.append(ToolCall(tool="update_policy_register", args={"policy_id": fields.policy_id, "change_summary": summary}))
    elif doc_type == DocType.content_takedown_request:
        calls.append(ToolCall(tool="escalate_to_legal", args={"case_summary": summary}))
    elif doc_type == DocType.vendor_onboarding_request:
        calls.append(ToolCall(tool="notify_owner", args={"team": "security", "message": f"Security questionnaire needed: {summary}"}))
    elif doc_type == DocType.exception_request:
        calls.append(ToolCall(tool="notify_owner", args={"team": "policy-ops", "message": f"Exception request to register: {summary}"}))
    return calls


def process_document(text: str, actor: str = "intake") -> ProcessResult:
    trace = Trace("process_document")
    with trace.span("classify") as sp:
        doc_type, score, margin = classify.classify(text)
        sp["attrs"].update(doc_type=doc_type.value, score=score, margin=margin)
    with trace.span("extract"):
        fields = classify.extract(text)
    conf = classify.confidence(doc_type, margin, fields, text)
    suspicious = classify.is_suspicious(text)
    route = "auto" if conf >= config.AUTO_ROUTE_CONFIDENCE and not suspicious else "review"
    audit.write(trace.trace_id, actor, "process_document", route, doc_type=doc_type.value, confidence=conf, suspicious=suspicious,
                requester=fields.requester, subject=fields.subject)
    actions: list[ActionResult] = []
    if route == "auto":
        for call in plan_actions(doc_type, fields):
            with trace.span("tool", tool=call.tool):
                actions.append(tools.dispatch(call, trace.trace_id))
    else:
        from .redact import redact_text
        store.get_store().append("review_queue", {"trace_id": trace.trace_id, "reason": "suspicious_text" if suspicious else "low_confidence",
                                                  "confidence": conf, "preview": redact_text(text[:200])})
    trace.finish()
    return ProcessResult(trace_id=trace.trace_id, doc_type=doc_type, classification_score=score, fields=fields,
                         confidence=conf, route=route, actions=actions)
