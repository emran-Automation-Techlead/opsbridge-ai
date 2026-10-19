"""AWS Lambda entry point for an API Gateway HTTP API (payload format 2.0).

Security model (fail closed):
- /health is open. Every other route needs the header `x-api-key` equal to a secret read from SSM Parameter Store (SecureString).
- /approvals/{id}/decision additionally needs `x-approver-token` (a second secret) and a named approver in the body.
- If a secret is not configured, the route returns 503 instead of running unprotected.
- Validation errors list only field names; they never echo the rejected value (no PII in responses or logs).
Environment: OPSBRIDGE_STORE=dynamodb, OPSBRIDGE_TABLE, OPSBRIDGE_KB, API_KEY_PARAM, APPROVER_TOKEN_PARAM (names of SSM parameters).
For local tests only, API_KEY / APPROVER_TOKEN may be set directly.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re

from pydantic import BaseModel, Field, ValidationError

from . import answer, tools, workflow

_MAX_BODY = 20_000
_cache: dict[str, str] = {}
HEADERS = {"Content-Type": "application/json", "Strict-Transport-Security": "max-age=31536000", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class DocBody(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_BODY)


class Decision(BaseModel):
    approver: str = Field(min_length=2, max_length=80)
    approve: bool


def _secret(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    param = os.environ.get(f"{name}_PARAM")
    if not param:
        return None
    if param not in _cache:
        import boto3
        _cache[param] = boto3.client("ssm").get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    return _cache[param]


def _resp(code: int, body) -> dict:
    return {"statusCode": code, "headers": HEADERS, "body": json.dumps(body, default=str)}


def _check(headers: dict, header: str, secret_name: str) -> dict | None:
    expected = _secret(secret_name)
    if not expected:
        return _resp(503, {"error": f"{secret_name} is not configured; route disabled"})
    given = headers.get(header, "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return _resp(401, {"error": "unauthorized"})
    return None


def handler(event: dict, context=None) -> dict:
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", ""), event.get("rawPath", "")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if method == "GET" and path == "/health":
        return _resp(200, {"status": "ok", "store": os.environ.get("OPSBRIDGE_STORE", "file")})

    denied = _check(headers, "x-api-key", "API_KEY")
    if denied:
        return denied
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    if len(raw) > _MAX_BODY + 2000:
        return _resp(413, {"error": "body too large"})
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid JSON"})

    try:
        if method == "POST" and path == "/ask":
            return _resp(200, answer.ask(AskBody(**body).question, actor="api").model_dump(mode="json"))
        if method == "POST" and path == "/documents":
            return _resp(200, workflow.process_document(DocBody(**body).text, actor="api").model_dump(mode="json"))
        if method == "GET" and path == "/approvals":
            return _resp(200, tools.list_approvals((event.get("queryStringParameters") or {}).get("status")))
        m = re.fullmatch(r"/approvals/([A-Za-z0-9]{1,16})/decision", path)
        if method == "POST" and m:
            denied = _check(headers, "x-approver-token", "APPROVER_TOKEN")
            if denied:
                return denied
            d = Decision(**body)
            return _resp(200, tools.decide(m.group(1), d.approver, d.approve))
    except ValidationError as exc:
        return _resp(422, {"error": "validation failed", "fields": sorted({str(e["loc"][-1]) for e in exc.errors() if e["loc"]})})
    except KeyError:
        return _resp(404, {"error": "unknown approval id"})
    except (PermissionError, ValueError) as exc:
        return _resp(409, {"error": str(exc)})
    return _resp(404, {"error": "not found"})
