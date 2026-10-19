# OpsBridge on AWS - live demo plan (needs approval before anything is created)

**Status: PLAN ONLY. Nothing has been created in AWS.** Tests for the cloud code run against a local AWS mock (moto).

## Why
To show the system answering real HTTPS requests from the cloud, with approvals and audit records stored in a managed database, so the story is "built, tested **and** run on AWS" - at a cost of cents, deleted straight after recording.

## Architecture (region ap-south-1, Mumbai)
```mermaid
flowchart LR
  C[curl / video demo] -->|HTTPS + x-api-key| A[API Gateway HTTP API - throttled 5 req/s]
  A --> L[Lambda opsbridge-live - python3.12 arm64 256 MB]
  L --> D[(DynamoDB opsbridge-live - audit, traces, tickets, approvals)]
  L --> S[SSM Parameter Store - API key + approver token, SecureString]
  L --> G[CloudWatch Logs - 3-day retention]
```
Answers are extractive (no LLM). **Bedrock is not used** and would be a separate, separately-approved step.

## Resources (all named `opsbridge-live*`, tagged `project=opsbridge`)
DynamoDB table (on-demand, TTL), CloudWatch log group (3 days), IAM role `opsbridge-live-lambda` (least privilege: this table, this log group, two parameters), two SSM SecureString parameters, Lambda function, HTTP API with throttling. **Not created:** EC2, RDS, NAT gateway, load balancer, KMS customer key, Secrets Manager, any Bedrock call.

## Cost estimate (order of magnitude; verify in the AWS Pricing Calculator)
For a demo of about 500 requests: Lambda inside the free tier; HTTP API about USD 0.0006; DynamoDB about USD 0.003; logs about USD 0.001; SSM and IAM free. **Total under about USD 0.01-0.05, paid from your credits first.** No hourly charges, so idle cost is about zero, and everything is deleted after recording. Budgets and alerts are not hard spending caps; the throttle (5 requests per second) and the teardown are the real limits.

## Permissions needed (least privilege)
Your `portfolio-readonly` user has only `ReadOnlyAccess`. Deploying needs the extra policy in `deploy/deployer-policy.json`: write access limited to the one table, one function, one role, one log group and `/opsbridge/live/*` parameters, in ap-south-1 only; API Gateway actions cannot be limited by name, so they cover HTTP APIs in the region. It grants **no** EC2, RDS, S3, Bedrock, billing, IAM-user or IAM-policy permissions.
Safest sequence: (1) attach the policy to `portfolio-readonly`; (2) deploy, record, destroy; (3) **detach the policy again**. The policy is derived from the exact calls in `deploy/aws_live.py`; if the first run needs one more permission, I will show you the exact addition before you grant it.

## Known risk: organisation restrictions
This account's organisation policy already denies listing Lambda, EC2, RDS, DynamoDB, ECR, EKS and CloudFormation in the regions I tried. Creating resources may be blocked too. `apply` creates the cheap resources first and **rolls everything back automatically** if any step is denied. If Lambda or API Gateway is blocked, the fallback is to keep the local demo (nothing is lost) or to ask the account owner to lift the restriction.

## Steps after approval
1. You attach the policy (or let me do it through Claude in Chrome while you watch; I never type your credentials).
2. `python deploy/build_lambda_zip.py` (2.5 MB package, built for Linux arm64).
3. `python deploy/aws_live.py plan --profile portfolio-readonly` (no changes) then `apply ... --yes-i-approved-the-cost-and-permissions`.
4. Smoke test `/health`; run the live demo (ask, process a document, approve) with the generated API key; capture evidence (responses, DynamoDB items, CloudWatch log lines) with account identifiers hidden.
5. `python deploy/aws_live.py destroy --profile portfolio-readonly`; confirm in the console and Billing that nothing remains; detach the policy.

## Rollback
`destroy` removes: API, Lambda, SSM parameters, role policy and role, log group, table, local secrets file. It is safe to run twice and runs automatically when `apply` fails.

## Approval checklist
- [ ] Region ap-south-1 and the resource list above
- [ ] Estimated cost under about USD 0.05 from credits
- [ ] Attach `deploy/deployer-policy.json` to `portfolio-readonly` temporarily
- [ ] Teardown right after recording
