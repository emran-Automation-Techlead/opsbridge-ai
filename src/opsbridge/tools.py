"""Allow-listed, schema-validated tools with an approval gate for high-impact actions.

The integrations are MOCKS that append to JSON-lines files under runs/ (tickets, notifications, register, legal cases).
A real deployment would replace the bodies with calls to the ticketing/policy systems; the gate and schemas stay the same.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from . import audit, store
from .models import ActionResult, DocType, Priority, ToolCall
from .redact import redact


class Team(str, Enum):
    policy_ops = "policy-ops"
    legal_ops = "legal-ops"
    security = "security"
    it = "it"
    content_ops = "content-ops"
    procurement = "procurement"


class CreateTicket(BaseModel):
    ticket_type: DocType
    summary: str = Field(min_length=3, max_length=200)
    priority: Priority
    owner_team: Team


class NotifyOwner(BaseModel):
    team: Team
    message: str = Field(min_length=3, max_length=300)


class UpdatePolicyRegister(BaseModel):
    policy_id: str = Field(pattern=r"^POL-\d{3}$")
    change_summary: str = Field(min_length=3, max_length=300)


class EscalateToLegal(BaseModel):
    case_summary: str = Field(min_length=3, max_length=300)


def _append(name: str, record: dict) -> str:
    rid = uuid.uuid4().hex[:8]
    store.get_store().append(name.removesuffix(".jsonl"), redact({"id": rid, "ts": datetime.now(timezone.utc).isoformat(), **record}))
    return rid


def _create_ticket(a: CreateTicket) -> str: return "ticket " + _append("tickets.jsonl", a.model_dump(mode="json"))
def _notify(a: NotifyOwner) -> str: return "notification " + _append("notifications.jsonl", a.model_dump(mode="json"))
def _register(a: UpdatePolicyRegister) -> str: return "register entry " + _append("register.jsonl", a.model_dump(mode="json"))
def _legal(a: EscalateToLegal) -> str: return "legal case " + _append("legal.jsonl", a.model_dump(mode="json"))


# name -> (args schema, impact, implementation)
REGISTRY: dict[str, tuple[type[BaseModel], str, Callable]] = {
    "create_ticket": (CreateTicket, "low", _create_ticket),
    "notify_owner": (NotifyOwner, "low", _notify),
    "update_policy_register": (UpdatePolicyRegister, "high", _register),
    "escalate_to_legal": (EscalateToLegal, "high", _legal),
}


# ---------------------------------------------------------------- approvals
def list_approvals(status: str | None = None) -> list[dict]:
    return [a for a in store.get_store().approvals_all() if status is None or a["status"] == status]


def dispatch(call: ToolCall, trace_id: str, actor: str = "workflow") -> ActionResult:
    """Run one proposed tool call through: allow-list -> schema validation -> approval gate -> execution."""
    if call.tool not in REGISTRY:
        audit.write(trace_id, actor, "tool_call", "not_allowed", tool=call.tool)
        return ActionResult(tool=call.tool, args=call.args, impact="unknown", status="not_allowed", detail="tool is not on the allow-list")
    schema, impact, fn = REGISTRY[call.tool]
    try:
        args = schema(**call.args)
    except ValidationError as exc:
        audit.write(trace_id, actor, "tool_call", "invalid", tool=call.tool, errors=[e["loc"] for e in exc.errors()])
        return ActionResult(tool=call.tool, args=call.args, impact=impact, status="invalid", detail="arguments failed schema validation")
    if impact == "high":
        aid = uuid.uuid4().hex[:8]
        store.get_store().approval_add({"id": aid, "tool": call.tool, "args": redact(args.model_dump(mode="json")), "status": "pending",
                                        "requested_at": datetime.now(timezone.utc).isoformat(), "trace_id": trace_id, "decided_by": None})
        audit.write(trace_id, actor, "tool_call", "pending_approval", tool=call.tool, approval_id=aid)
        return ActionResult(tool=call.tool, args=args.model_dump(mode="json"), impact=impact, status="pending_approval", approval_id=aid,
                            detail="high-impact action waits for a human approver")
    detail = fn(args)
    audit.write(trace_id, actor, "tool_call", "executed", tool=call.tool, detail=detail)
    return ActionResult(tool=call.tool, args=args.model_dump(mode="json"), impact=impact, status="executed", detail=detail)


def decide(approval_id: str, approver: str, approve: bool) -> dict:
    """Human decision. The approver must be a named human (not the workflow). The status change is atomic: only one decision can win."""
    if not approver or approver == "workflow":
        raise PermissionError("approver must be a named human, not the workflow")
    st = store.get_store()
    st.approval_get(approval_id)  # KeyError if unknown
    a = st.approval_transition(approval_id, "pending", "approved" if approve else "rejected",
                               decided_by=approver, decided_at=datetime.now(timezone.utc).isoformat())
    if approve:
        schema, _, fn = REGISTRY[a["tool"]]
        try:
            a = st.approval_update(approval_id, result=fn(schema(**a["args"])))
        except Exception as exc:  # approved but the tool failed: keep the evidence, then surface the error
            st.approval_update(approval_id, result=f"ERROR: {type(exc).__name__}")
            audit.write(a["trace_id"], approver, "approval", "approved_but_tool_failed", approval_id=approval_id, tool=a["tool"])
            raise
    audit.write(a["trace_id"], approver, "approval", a["status"], approval_id=approval_id, tool=a["tool"])
    return a
