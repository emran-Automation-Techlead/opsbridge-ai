"""FastAPI service. Reading/asking is open to the internal network by design; the APPROVAL endpoint is locked:
- it is disabled (503) unless OPSBRIDGE_APPROVER_TOKEN is set,
- it needs the header X-Approver-Token (constant-time compared) and a named approver.
In production, put the whole API behind your identity provider (OIDC / API Gateway authorizer); the token is a minimal local control."""
from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import answer, tools, workflow

app = FastAPI(title="OpsBridge AI", version="0.1.0")


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class DocBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class Decision(BaseModel):
    approver: str = Field(min_length=2, max_length=80)
    approve: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(body: AskBody):
    return answer.ask(body.question)


@app.post("/documents")
def documents(body: DocBody):
    return workflow.process_document(body.text, actor="api")


@app.get("/approvals")
def approvals(status: str | None = None):
    return tools.list_approvals(status)


@app.post("/approvals/{approval_id}/decision")
def decide(approval_id: str, body: Decision, x_approver_token: str | None = Header(default=None)):
    expected = os.environ.get("OPSBRIDGE_APPROVER_TOKEN")
    if not expected:
        raise HTTPException(503, "approval endpoint is disabled: OPSBRIDGE_APPROVER_TOKEN is not set")
    if not x_approver_token or not hmac.compare_digest(x_approver_token, expected):
        raise HTTPException(401, "invalid approver token")
    try:
        return tools.decide(approval_id, body.approver, body.approve)
    except KeyError:
        raise HTTPException(404, "unknown approval id")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc))
