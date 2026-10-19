"""Deploy / destroy the OpsBridge live demo on AWS (Mumbai, ap-south-1 by default). Uses boto3 with a NAMED profile you choose.

    python deploy/aws_live.py plan    --profile NAME          # default: prints resources + cost estimate, makes NO AWS calls that change anything
    python deploy/aws_live.py apply   --profile NAME --yes-i-approved-the-cost-and-permissions
    python deploy/aws_live.py destroy --profile NAME

Design: HTTP API (throttled) -> Lambda (arm64, 256 MB) -> DynamoDB on-demand. Secrets (API key, approver token) are generated here, stored as
SSM SecureString, and written to deploy/.live-secrets.json (git-ignored) - they are never printed. Every resource is named opsbridge-live*
and tagged project=opsbridge, so teardown is complete and checkable. If any step of `apply` fails, everything created so far is removed.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "opsbridge-live"
PARAM_API = "/opsbridge/live/api-key"
PARAM_TOK = "/opsbridge/live/approver-token"
TAGS = {"project": "opsbridge", "purpose": "portfolio-demo", "teardown": "after-recording"}
SECRETS_FILE = ROOT / "deploy" / ".live-secrets.json"
THROTTLE = {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5.0}


def estimate(requests: int = 500) -> list[tuple[str, str]]:
    """Order-of-magnitude estimate from published on-demand prices (verify in the AWS Pricing Calculator; not a quote)."""
    return [
        (f"Lambda: {requests} requests x ~50 ms x 256 MB", "inside the free tier (1M requests + 400,000 GB-s per month) -> about USD 0.00"),
        (f"API Gateway HTTP API: {requests} requests", f"about USD {requests / 1e6 * 1.2:.4f} (roughly USD 1.00-1.20 per million)"),
        (f"DynamoDB on-demand: ~{requests * 4} writes + reads", f"about USD {requests * 4 / 1e6 * 1.5:.4f} (writes roughly USD 1.25-1.5 per million)"),
        ("CloudWatch Logs: ~1 MB ingested, 3-day retention", "about USD 0.001"),
        ("SSM Parameter Store (standard SecureString), IAM role", "USD 0.00"),
        ("Idle cost after the demo", "about USD 0.00 (no hourly resources); resources are deleted anyway"),
        ("TOTAL for a demo of this size", f"under USD 0.01-0.05, paid from your USD 120 credits first"),
    ]


def plan_text(region: str) -> str:
    lines = [f"Region: {region}", "", "Would create (all names start with 'opsbridge-live', tagged project=opsbridge):",
             "  1. DynamoDB table opsbridge-live (on-demand, TTL on 'ttl')", "  2. CloudWatch log group /aws/lambda/opsbridge-live (3-day retention)",
             "  3. IAM role opsbridge-live-lambda with a least-privilege inline policy (this table, this log group, two SSM parameters)",
             f"  4. SSM SecureString parameters {PARAM_API} and {PARAM_TOK} (random values, never printed)",
             "  5. Lambda function opsbridge-live (python3.12, arm64, 256 MB, 10 s timeout) from dist/opsbridge-lambda.zip",
             f"  6. API Gateway HTTP API opsbridge-live, default route -> Lambda, throttled to {THROTTLE['ThrottlingRateLimit']:.0f} req/s (burst {THROTTLE['ThrottlingBurstLimit']})",
             "", "Estimated cost:"]
    lines += [f"  - {a}: {b}" for a, b in estimate()]
    lines += ["", "Rollback: `python deploy/aws_live.py destroy --profile NAME` removes all of the above (also runs automatically if apply fails).",
              "Not created: no EC2, no RDS, no NAT gateway, no load balancer, no Bedrock calls, no KMS customer key, no Secrets Manager."]
    return "\n".join(lines)


MIN_CREDITS_USD = 20.0


def check_free_plan(session) -> float:
    """Refuse to deploy unless the account is on the AWS FREE plan (usage is paid from credits, never billed) with credits left.
    Raises RuntimeError otherwise. Uses the read-only Free Tier API; there is deliberately no flag to skip this from the command line."""
    state = session.client("freetier", region_name="us-east-1").get_account_plan_state()
    plan, status = state.get("accountPlanType"), state.get("accountPlanStatus")
    credits = float((state.get("accountPlanRemainingCredits") or {}).get("amount", 0))
    if plan != "FREE" or status != "ACTIVE":
        raise RuntimeError(f"account plan is {plan}/{status}, not FREE/ACTIVE: refusing to create anything that could be billed")
    if credits < MIN_CREDITS_USD:
        raise RuntimeError(f"only USD {credits:.2f} of credits left (minimum {MIN_CREDITS_USD:.0f}): refusing to deploy")
    return credits


def _tags_list(): return [{"Key": k, "Value": v} for k, v in TAGS.items()]


def apply(session, region: str, zip_path: Path, smoke: bool = True, check_plan: bool = True) -> dict:
    if check_plan:
        print(f"Free plan confirmed: USD {check_free_plan(session):.2f} of credits remaining (usage is paid from credits).")
    sts = session.client("sts"); account = sts.get_caller_identity()["Account"]
    iam, ddb, logs, lam, ssm, apig = (session.client(s, region_name=region) for s in ("iam", "dynamodb", "logs", "lambda", "ssm", "apigatewayv2"))
    iam = session.client("iam")
    done: list = []
    table_arn = f"arn:aws:dynamodb:{region}:{account}:table/{NAME}"
    log_group = f"/aws/lambda/{NAME}"
    role_name = f"{NAME}-lambda"
    try:
        ddb.create_table(TableName=NAME, BillingMode="PAY_PER_REQUEST", Tags=_tags_list(),
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        done.append("table"); ddb.get_waiter("table_exists").wait(TableName=NAME)
        ddb.update_time_to_live(TableName=NAME, TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"})
        logs.create_log_group(logGroupName=log_group, tags=TAGS); done.append("log_group")
        logs.put_retention_policy(logGroupName=log_group, retentionInDays=3)
        iam.create_role(RoleName=role_name, Tags=_tags_list(), AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}))
        done.append("role")
        iam.put_role_policy(RoleName=role_name, PolicyName="least-privilege", PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": f"arn:aws:logs:{region}:{account}:log-group:{log_group}:*"},
            {"Effect": "Allow", "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"], "Resource": table_arn},
            {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": f"arn:aws:ssm:{region}:{account}:parameter/opsbridge/live/*"}]}))
        sec = {"api_key": secrets.token_urlsafe(32), "approver_token": secrets.token_urlsafe(32)}
        ssm.put_parameter(Name=PARAM_API, Value=sec["api_key"], Type="SecureString", Tags=_tags_list()); done.append("ssm_api")
        ssm.put_parameter(Name=PARAM_TOK, Value=sec["approver_token"], Type="SecureString", Tags=_tags_list()); done.append("ssm_tok")
        role_arn = f"arn:aws:iam::{account}:role/{role_name}"
        fn_arn = None
        for attempt in range(12):  # a new IAM role needs a few seconds to become assumable
            try:
                fn_arn = lam.create_function(
                    FunctionName=NAME, Runtime="python3.12", Role=role_arn, Handler="opsbridge.lambda_handler.handler", Architectures=["arm64"],
                    Code={"ZipFile": zip_path.read_bytes()}, Timeout=10, MemorySize=256, Tags=TAGS,
                    Environment={"Variables": {"OPSBRIDGE_STORE": "dynamodb", "OPSBRIDGE_TABLE": NAME, "OPSBRIDGE_KB": "/var/task/data/kb",
                                               "API_KEY_PARAM": PARAM_API, "APPROVER_TOKEN_PARAM": PARAM_TOK, "OPSBRIDGE_RETENTION_DAYS": "7"}})["FunctionArn"]
                break
            except lam.exceptions.InvalidParameterValueException:
                time.sleep(5)
        if not fn_arn:
            raise RuntimeError("Lambda could not assume the new role after waiting")
        done.append("lambda")
        lam.get_waiter("function_active_v2").wait(FunctionName=NAME)
        api = apig.create_api(Name=NAME, ProtocolType="HTTP", Target=fn_arn, Tags=TAGS); done.append("api")
        apig.update_stage(ApiId=api["ApiId"], StageName="$default", DefaultRouteSettings=THROTTLE)
        lam.add_permission(FunctionName=NAME, StatementId="apigw-invoke", Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
                           SourceArn=f"arn:aws:execute-api:{region}:{account}:{api['ApiId']}/*/*")
        SECRETS_FILE.write_text(json.dumps({**sec, "endpoint": api["ApiEndpoint"], "region": region}), encoding="utf-8")
        if smoke:
            time.sleep(3)
            with urllib.request.urlopen(api["ApiEndpoint"] + "/health", timeout=30) as r:
                print("smoke test /health ->", r.status, r.read().decode()[:80])
        print("DEPLOYED. endpoint written to deploy/.live-secrets.json (git-ignored); secrets were not printed.")
        return {"api_id": api["ApiId"], "endpoint": api["ApiEndpoint"]}
    except Exception as exc:
        print(f"APPLY FAILED ({type(exc).__name__}: {str(exc)[:200]}) - rolling back what was created:", done)
        destroy(session, region)
        raise


def destroy(session, region: str) -> list[str]:
    ddb, logs, lam, ssm, apig = (session.client(s, region_name=region) for s in ("dynamodb", "logs", "lambda", "ssm", "apigatewayv2"))
    iam = session.client("iam")
    removed = []

    def attempt(label, fn):
        try:
            fn(); removed.append(label)
        except Exception as exc:  # already gone or not allowed: report, keep going
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            if code not in ("ResourceNotFoundException", "NoSuchEntity", "NotFoundException", "ParameterNotFound"):
                print(f"  could not remove {label}: {code}")
    try:
        for a in apig.get_apis()["Items"]:
            if a["Name"] == NAME:
                attempt(f"api {a['ApiId']}", lambda a=a: apig.delete_api(ApiId=a["ApiId"]))
    except Exception as exc:
        print("  could not list APIs:", type(exc).__name__)
    attempt("lambda", lambda: lam.delete_function(FunctionName=NAME))
    attempt("ssm api key", lambda: ssm.delete_parameter(Name=PARAM_API))
    attempt("ssm approver token", lambda: ssm.delete_parameter(Name=PARAM_TOK))
    attempt("role policy", lambda: iam.delete_role_policy(RoleName=f"{NAME}-lambda", PolicyName="least-privilege"))
    attempt("role", lambda: iam.delete_role(RoleName=f"{NAME}-lambda"))
    attempt("log group", lambda: logs.delete_log_group(logGroupName=f"/aws/lambda/{NAME}"))
    attempt("table", lambda: ddb.delete_table(TableName=NAME))
    if SECRETS_FILE.exists():
        SECRETS_FILE.unlink(); removed.append("local secrets file")
    print("removed:", removed or "nothing found")
    return removed


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["plan", "apply", "destroy"], nargs="?", default="plan")
    p.add_argument("--profile"); p.add_argument("--region", default="ap-south-1")
    p.add_argument("--zip", default=str(ROOT / "dist" / "opsbridge-lambda.zip"))
    p.add_argument("--yes-i-approved-the-cost-and-permissions", action="store_true")
    a = p.parse_args(argv)
    if a.mode == "plan":
        print(plan_text(a.region)); return 0
    if not a.profile:
        p.error("--profile is required (never relies on the default profile)")
    if a.mode == "apply":
        if not a.yes_i_approved_the_cost_and_permissions:
            p.error("apply needs --yes-i-approved-the-cost-and-permissions")
        if not Path(a.zip).exists():
            p.error("build the package first: python deploy/build_lambda_zip.py")
    import boto3
    session = boto3.Session(profile_name=a.profile)
    if a.mode == "destroy":
        destroy(session, a.region); return 0
    apply(session, a.region, Path(a.zip)); return 0


if __name__ == "__main__":
    sys.exit(main())
