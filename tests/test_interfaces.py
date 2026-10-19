import asyncio

import pytest
from fastapi.testclient import TestClient

from opsbridge import config, evaluate, providers, tools
from opsbridge.api import app
from opsbridge.models import ToolCall
from opsbridge.providers import BedrockProvider

client = TestClient(app)
HIGH = ToolCall(tool="update_policy_register", args={"policy_id": "POL-003", "change_summary": "Reorder review step"})


# ---------------------------------------------------------------- SPEC-008
@pytest.mark.spec("SPEC-008")
def test_approval_endpoint_disabled_without_token(monkeypatch):
    monkeypatch.delenv("OPSBRIDGE_APPROVER_TOKEN", raising=False)
    aid = tools.dispatch(HIGH, "t").approval_id
    assert client.post(f"/approvals/{aid}/decision", json={"approver": "Dana Wu", "approve": True}).status_code == 503


@pytest.mark.spec("SPEC-008")
def test_approval_endpoint_rejects_wrong_and_missing_token(monkeypatch):
    monkeypatch.setenv("OPSBRIDGE_APPROVER_TOKEN", "s3cret-token")
    aid = tools.dispatch(HIGH, "t").approval_id
    body = {"approver": "Dana Wu", "approve": True}
    assert client.post(f"/approvals/{aid}/decision", json=body).status_code == 401
    assert client.post(f"/approvals/{aid}/decision", json=body, headers={"X-Approver-Token": "wrong"}).status_code == 401
    assert not (config.runs_dir() / "register.jsonl").exists()


@pytest.mark.spec("SPEC-008")
def test_approval_endpoint_accepts_correct_token_once(monkeypatch):
    monkeypatch.setenv("OPSBRIDGE_APPROVER_TOKEN", "s3cret-token")
    aid = tools.dispatch(HIGH, "t").approval_id
    h = {"X-Approver-Token": "s3cret-token"}
    r = client.post(f"/approvals/{aid}/decision", json={"approver": "Dana Wu", "approve": True}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/approvals/{aid}/decision", json={"approver": "Dana Wu", "approve": True}, headers=h).status_code == 409
    assert client.post("/approvals/nope/decision", json={"approver": "Dana Wu", "approve": True}, headers=h).status_code == 404


@pytest.mark.spec("SPEC-008")
def test_api_ask_documents_and_validation():
    assert client.get("/health").json() == {"status": "ok"}
    a = client.post("/ask", json={"question": "How long are audit logs retained?"}).json()
    assert a["citations"][0]["doc_id"] == "POL-010"
    d = client.post("/documents", json={"text": "From: A Person (Ops)\nSubject: Read access to repository\nPriority: Low\n\nPlease grant access to the content repository."}).json()
    assert d["doc_type"] == "access_request"
    assert client.post("/ask", json={"question": "x"}).status_code == 422


# ---------------------------------------------------------------- SPEC-009
@pytest.mark.spec("SPEC-009")
def test_quality_gate_passes_on_current_build():
    res = evaluate.run()
    assert res["passed"], res["failures"]
    assert res["metrics"]["unsafe_executions"] == 0


@pytest.mark.spec("SPEC-009")
def test_quality_gate_fails_when_quality_drops(monkeypatch):
    monkeypatch.setattr(config, "ABSTAIN_THRESHOLD", 0.95)  # abstains on almost everything
    res = evaluate.run()
    assert not res["passed"] and not res["gates"]["false_abstain_rate"]


# ---------------------------------------------------------------- SPEC-010
class StubClient:
    def __init__(self, text): self.text, self.calls = text, 0

    def converse(self, **kw):
        self.calls += 1
        return {"output": {"message": {"content": [{"text": self.text}]}}}


def _ask_with(text):
    from opsbridge import answer
    stub = StubClient(text)
    return answer.ask("How long is published content kept before it is archived?", provider=BedrockProvider("test-model", client=stub)), stub


@pytest.mark.spec("SPEC-010")
def test_llm_answer_with_valid_citation_is_used():
    a, stub = _ask_with("Published content is kept 24 months [1].")
    assert a.provider == "bedrock" and a.answer.endswith("[1].") and stub.calls == 1


@pytest.mark.spec("SPEC-010")
@pytest.mark.parametrize("text", ["Content is kept forever.", "Kept 24 months [7].", "INSUFFICIENT"])
def test_llm_answer_without_valid_citation_falls_back(text):
    a, _ = _ask_with(text)
    assert a.provider == "extractive" and "24 months" in a.answer


@pytest.mark.spec("SPEC-010")
def test_llm_is_off_by_default_and_bedrock_needs_explicit_model(monkeypatch):
    assert providers.get_provider().name == "extractive"
    monkeypatch.setenv("OPSBRIDGE_LLM", "bedrock")
    monkeypatch.delenv("OPSBRIDGE_BEDROCK_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        providers.get_provider()


@pytest.mark.spec("SPEC-010")
def test_pii_is_redacted_before_text_goes_to_the_llm():
    stub = StubClient("ok [1]")
    captured = {}
    orig = stub.converse
    stub.converse = lambda **kw: (captured.update(kw), orig(**kw))[1]
    BedrockProvider("m", client=stub).compose("contact jane@example.com?", ["call +91 98765 43210"])
    prompt = captured["messages"][0]["content"][0]["text"]
    assert "jane@example.com" not in prompt and "98765" not in prompt


# ---------------------------------------------------------------- SPEC-011
@pytest.mark.spec("SPEC-011")
def test_mcp_exposes_only_safe_tools():
    from opsbridge import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert names == {"ask_policy", "classify_document"}
    assert not any("approv" in n or "decid" in n for n in names)


@pytest.mark.spec("SPEC-011")
def test_mcp_tools_work():
    from opsbridge import mcp_server
    assert mcp_server.ask_policy("How long are audit logs retained?")["citations"][0]["doc_id"] == "POL-010"
    assert mcp_server.classify_document("Subject: Copyright takedown\n\nplease remove the content, copyright notice")["doc_type"] == "content_takedown_request"


def test_every_spec_has_at_least_one_test(spec_map):
    from conftest import spec_ids
    missing = [s for s in spec_ids() if not spec_map.get(s)]
    assert not missing, f"specs without tests: {missing}"
