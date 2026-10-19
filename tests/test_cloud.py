"""Cloud-path tests. They run against moto (a local AWS mock): no AWS account, no network, no cost."""
import json
import threading

import boto3
import pytest
from moto import mock_aws

from opsbridge import audit, lambda_handler, store, tools
from opsbridge.models import ToolCall

TABLE = "opsbridge-test"
HIGH = ToolCall(tool="update_policy_register", args={"policy_id": "POL-003", "change_summary": "Reorder review step"})
ASK = {"question": "How long are audit logs retained?"}


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-south-1").create_table(
            TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        monkeypatch.setenv("OPSBRIDGE_STORE", "dynamodb")
        monkeypatch.setenv("OPSBRIDGE_TABLE", TABLE)
        store.reset_cache()
        lambda_handler._cache.clear()
        yield


def ev(method, path, body=None, headers=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path, "headers": headers or {}, "body": json.dumps(body) if body is not None else None}


KEY = {"x-api-key": "k-123"}
TOK = {"x-api-key": "k-123", "x-approver-token": "t-456"}


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("API_KEY", "k-123")
    monkeypatch.setenv("APPROVER_TOKEN", "t-456")


@pytest.mark.spec("SPEC-012")
def test_dynamo_store_matches_file_behaviour(cloud):
    r = tools.dispatch(HIGH, "t1")
    assert r.status == "pending_approval"
    assert [a["id"] for a in tools.list_approvals("pending")] == [r.approval_id]
    done = tools.decide(r.approval_id, "Dana Wu", True)
    assert done["status"] == "approved" and done["result"].startswith("register entry")
    assert store.get_store().read("register")[0]["policy_id"] == "POL-003"
    assert any(e["action"] == "approval" and e["outcome"] == "approved" for e in audit.read_all())


@pytest.mark.spec("SPEC-012")
def test_second_decision_is_refused(cloud):
    aid = tools.dispatch(HIGH, "t1").approval_id
    tools.decide(aid, "Dana Wu", True)
    with pytest.raises(ValueError):
        tools.decide(aid, "Someone Else", False)
    assert tools.list_approvals()[0]["decided_by"] == "Dana Wu"


@pytest.mark.spec("SPEC-012")
def test_concurrent_decisions_only_one_wins(cloud):
    aid = tools.dispatch(HIGH, "t1").approval_id
    outcomes = []

    def go(name, approve):
        try:
            tools.decide(aid, name, approve)
            outcomes.append("ok")
        except ValueError:
            outcomes.append("refused")

    threads = [threading.Thread(target=go, args=(f"Person {i}", i % 2 == 0)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 1 and outcomes.count("refused") == 5


@pytest.mark.spec("SPEC-013")
def test_health_is_open_everything_else_needs_key(cloud, secrets):
    assert lambda_handler.handler(ev("GET", "/health"))["statusCode"] == 200
    assert lambda_handler.handler(ev("POST", "/ask", ASK))["statusCode"] == 401
    assert lambda_handler.handler(ev("POST", "/ask", ASK, {"x-api-key": "wrong"}))["statusCode"] == 401


@pytest.mark.spec("SPEC-013")
def test_unconfigured_secret_fails_closed(cloud, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_PARAM", raising=False)
    assert lambda_handler.handler(ev("POST", "/ask", ASK, KEY))["statusCode"] == 503


@pytest.mark.spec("SPEC-013")
def test_ask_and_documents_work_and_are_stored_in_the_cloud_store(cloud, secrets):
    a = lambda_handler.handler(ev("POST", "/ask", ASK, KEY))
    assert a["statusCode"] == 200 and json.loads(a["body"])["citations"][0]["doc_id"] == "POL-010"
    text = "From: Marcus Lee (Legal Operations)\nSubject: Copyright takedown for article\nPriority: High\n\nA copyright notice arrived, please remove the content."
    d = lambda_handler.handler(ev("POST", "/documents", {"text": text}, KEY))
    body = json.loads(d["body"])
    assert body["doc_type"] == "content_takedown_request" and {x["status"] for x in body["actions"]} == {"executed", "pending_approval"}
    assert store.get_store().read("tickets") and store.get_store().read("trace")
    assert d["headers"]["X-Content-Type-Options"] == "nosniff"


@pytest.mark.spec("SPEC-013")
def test_approval_needs_second_secret_and_works_once(cloud, secrets):
    aid = tools.dispatch(HIGH, "t").approval_id
    url = f"/approvals/{aid}/decision"
    body = {"approver": "Dana Wu", "approve": True}
    assert lambda_handler.handler(ev("POST", url, body, KEY))["statusCode"] == 401
    assert lambda_handler.handler(ev("POST", url, body, {"x-api-key": "k-123", "x-approver-token": "bad"}))["statusCode"] == 401
    ok = lambda_handler.handler(ev("POST", url, body, TOK))
    assert ok["statusCode"] == 200 and json.loads(ok["body"])["status"] == "approved"
    assert lambda_handler.handler(ev("POST", url, body, TOK))["statusCode"] == 409
    assert lambda_handler.handler(ev("POST", "/approvals/zzzz/decision", body, TOK))["statusCode"] == 404


@pytest.mark.spec("SPEC-013")
def test_validation_errors_do_not_echo_input(cloud, secrets):
    r = lambda_handler.handler(ev("POST", "/documents", {"text": ""}, KEY))
    assert r["statusCode"] == 422 and json.loads(r["body"])["fields"] == ["text"]
    r2 = lambda_handler.handler(ev("POST", "/ask", {"question": "jane@example.com"[:2]}, KEY))
    assert r2["statusCode"] == 422 and "ja" not in r2["body"]
    raw = {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/ask", "headers": KEY, "body": "{not json jane@example.com"}
    r3 = lambda_handler.handler(raw)
    assert r3["statusCode"] == 400 and "jane@example.com" not in r3["body"]


@pytest.mark.spec("SPEC-013")
def test_unknown_route_and_large_body(cloud, secrets):
    assert lambda_handler.handler(ev("GET", "/nope", None, KEY))["statusCode"] == 404
    assert lambda_handler.handler(ev("POST", "/documents", {"text": "a" * 30000}, KEY))["statusCode"] == 413


@pytest.mark.spec("SPEC-013")
def test_secrets_can_come_from_ssm(cloud, monkeypatch):
    boto3.client("ssm", region_name="ap-south-1").put_parameter(Name="/opsbridge/api-key", Value="from-ssm", Type="SecureString")
    monkeypatch.setenv("API_KEY_PARAM", "/opsbridge/api-key")
    monkeypatch.delenv("API_KEY", raising=False)
    assert lambda_handler.handler(ev("POST", "/ask", ASK, {"x-api-key": "from-ssm"}))["statusCode"] == 200
    assert lambda_handler.handler(ev("POST", "/ask", ASK, KEY))["statusCode"] == 401
