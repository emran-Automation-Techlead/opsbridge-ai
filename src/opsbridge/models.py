"""Typed data contracts (Pydantic v2). These are the schemas the tools, API and evaluation rely on."""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):
    policy_change_request = "policy_change_request"
    content_takedown_request = "content_takedown_request"
    vendor_onboarding_request = "vendor_onboarding_request"
    access_request = "access_request"
    exception_request = "exception_request"
    unknown = "unknown"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    quote: str


class Answer(BaseModel):
    trace_id: str
    question: str
    answer: str
    abstained: bool
    confidence: float
    citations: list[Citation] = Field(default_factory=list)
    provider: str = "extractive"


class ExtractedRequest(BaseModel):
    requester: str | None = None
    department: str | None = None
    subject: str | None = None
    priority: Priority = Priority.medium
    due_date: date | None = None
    policy_id: str | None = None


class ToolCall(BaseModel):
    tool: str
    args: dict


class ActionResult(BaseModel):
    tool: str
    args: dict
    impact: str
    status: str  # executed | pending_approval | rejected | invalid | not_allowed
    detail: str = ""
    approval_id: str | None = None


class ProcessResult(BaseModel):
    trace_id: str
    doc_type: DocType
    classification_score: float
    fields: ExtractedRequest
    confidence: float
    route: str  # auto | review
    actions: list[ActionResult] = Field(default_factory=list)
