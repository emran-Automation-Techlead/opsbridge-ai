"""Tests for deploy/aws_live.py against moto (local AWS mock). No real AWS account, no network, no cost."""
import importlib.util
import json
import zipfile
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aws_live", ROOT / "deploy" / "aws_live.py")
aws_live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aws_live)
REGION = "ap-southeast-2"


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setattr(aws_live, "SECRETS_FILE", tmp_path / "live-secrets.json")
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("opsbridge/lambda_handler.py", "def handler(e, c=None):\n    return {'statusCode': 200}\n")
    with mock_aws():
        yield boto3.Session(region_name=REGION), z


def _inventory(session):
    return {
        "tables": session.client("dynamodb", region_name=REGION).list_tables()["TableNames"],
        "functions": [f["FunctionName"] for f in session.client("lambda", region_name=REGION).list_functions()["Functions"]],
        "apis": [a["Name"] for a in session.client("apigatewayv2", region_name=REGION).get_apis()["Items"]],
        "roles": [r["RoleName"] for r in session.client("iam").list_roles()["Roles"]],
        "params": [p["Name"] for p in session.client("ssm", region_name=REGION).describe_parameters()["Parameters"]],
        "log_groups": [g["logGroupName"] for g in session.client("logs", region_name=REGION).describe_log_groups()["logGroups"]],
    }


@pytest.mark.spec("SPEC-014")
def test_plan_mode_prints_cost_and_makes_no_aws_calls(capsys):
    assert aws_live.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "Estimated cost" in out and "Rollback" in out and "no Bedrock calls" in out and "ap-southeast-2" in out


@pytest.mark.spec("SPEC-014")
def test_apply_needs_an_explicit_profile_and_approval_flag():
    with pytest.raises(SystemExit):
        aws_live.main(["apply"])
    with pytest.raises(SystemExit):
        aws_live.main(["apply", "--profile", "x"])


@pytest.mark.spec("SPEC-014")
def test_apply_creates_everything_with_safe_settings_then_destroy_removes_everything(cloud, monkeypatch):
    session, z = cloud
    real, calls = session.client, []

    def client(name, *a, **k):
        c = real(name, *a, **k)
        if name == "apigatewayv2":  # moto does not implement update_stage: record the call so the throttle settings are still verified
            c.update_stage = lambda **kw: calls.append(kw)
        return c
    monkeypatch.setattr(session, "client", client)
    aws_live.apply(session, REGION, z, smoke=False, check_plan=False)
    assert calls and calls[0]["StageName"] == "$default" and calls[0]["DefaultRouteSettings"] == {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5.0}
    inv = _inventory(session)
    assert inv["tables"] == ["opsbridge-live"] and inv["functions"] == ["opsbridge-live"] and inv["apis"] == ["opsbridge-live"]
    assert "opsbridge-live-lambda" in inv["roles"] and set(inv["params"]) == {aws_live.PARAM_API, aws_live.PARAM_TOK}
    assert inv["log_groups"] == ["/aws/lambda/opsbridge-live"]
    fn = session.client("lambda", region_name=REGION).get_function(FunctionName="opsbridge-live")["Configuration"]
    assert fn["Runtime"] == "python3.12" and fn["Architectures"] == ["arm64"] and fn["Timeout"] == 10
    env = fn["Environment"]["Variables"]
    assert env["OPSBRIDGE_STORE"] == "dynamodb" and "API_KEY" not in env and "APPROVER_TOKEN" not in env  # only parameter NAMES in the environment
    saved = json.loads(aws_live.SECRETS_FILE.read_text(encoding="utf-8"))
    assert len(saved["api_key"]) >= 32 and saved["api_key"] != saved["approver_token"]
    ssm_val = session.client("ssm", region_name=REGION).get_parameter(Name=aws_live.PARAM_API, WithDecryption=True)["Parameter"]["Value"]
    assert ssm_val == saved["api_key"]
    pol = session.client("iam").get_role_policy(RoleName="opsbridge-live-lambda", PolicyName="least-privilege")["PolicyDocument"]
    resources = json.dumps(pol)
    assert '"*"' not in resources and "dynamodb:Scan" not in resources and "dynamodb:DeleteItem" not in resources
    aws_live.destroy(session, REGION)
    monkeypatch.undo()
    assert all(not v for v in _inventory(session).values())
    assert not aws_live.SECRETS_FILE.exists()


@pytest.mark.spec("SPEC-014")
def test_failed_apply_rolls_back_everything(cloud, monkeypatch):
    session, z = cloud
    real = session.client

    class Boom:
        def __init__(self, inner): self._i = inner
        def __getattr__(self, name): return getattr(self._i, name)

    def client(name, *a, **k):
        c = real(name, *a, **k)
        if name == "lambda":
            c.create_function = lambda **kw: (_ for _ in ()).throw(RuntimeError("AccessDenied by an organisation policy"))
        return c
    monkeypatch.setattr(session, "client", client)
    with pytest.raises(RuntimeError):
        aws_live.apply(session, REGION, z, smoke=False, check_plan=False)
    monkeypatch.undo()
    assert all(not v for v in _inventory(session).values())


@pytest.mark.spec("SPEC-014")
def test_destroy_is_safe_to_run_twice(cloud):
    session, _ = cloud
    assert aws_live.destroy(session, REGION) == []
    assert aws_live.destroy(session, REGION) == []


class _FakeFreeTier:
    def __init__(self, plan="FREE", status="ACTIVE", credits=120.0): self.s = {"accountPlanType": plan, "accountPlanStatus": status, "accountPlanRemainingCredits": {"amount": credits, "unit": "USD"}}
    def get_account_plan_state(self): return self.s


class _FakeSession:
    def __init__(self, ft): self.ft = ft
    def client(self, name, **kw):
        assert name == "freetier"
        return self.ft


@pytest.mark.spec("SPEC-014")
def test_plan_guard_allows_only_free_plan_with_credits():
    assert aws_live.check_free_plan(_FakeSession(_FakeFreeTier())) == 120.0
    for bad in (_FakeFreeTier(plan="PAID"), _FakeFreeTier(status="CLOSED"), _FakeFreeTier(credits=5.0)):
        with pytest.raises(RuntimeError):
            aws_live.check_free_plan(_FakeSession(bad))


@pytest.mark.spec("SPEC-014")
def test_apply_creates_nothing_when_the_plan_guard_fails(cloud):
    session, z = cloud
    with pytest.raises(RuntimeError):
        aws_live.apply(_FakeSession(_FakeFreeTier(plan="PAID")), REGION, z, smoke=False)
    assert all(not v for v in _inventory(session).values())
