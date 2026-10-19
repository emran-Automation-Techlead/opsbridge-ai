# Specifications (acceptance criteria)

Spec-driven development: each requirement below is written first as Given / When / Then. Every spec must be linked to at least one automated test with `@pytest.mark.spec("SPEC-0xx")`;
the test suite fails if a spec has no test, and `docs/TRACEABILITY.md` is regenerated on every run.

## SPEC-001 Grounded answers with citations
Given a question that the knowledge base can answer, When it is asked, Then the answer is drawn from the retrieved text and includes at least one citation (document id, chunk id, quote).

## SPEC-002 Abstain when evidence is insufficient
Given a question outside the knowledge base (or an instruction-style question), When it is asked, Then the system abstains, says so, returns no citations and records the abstention in the audit log.

## SPEC-003 Classification, extraction and human review
Given an incoming request document, When it is processed, Then it is classified, its fields are extracted and validated, and a confidence score is computed; below the confidence threshold or when it contains instruction-like text, it goes to the human review queue and no tool runs.

## SPEC-004 Allow-listed, schema-validated tools
Given a proposed tool call, When it is dispatched, Then unknown tools are refused, invalid arguments are refused, and nothing runs outside the allow-list.

## SPEC-005 Human approval for high-impact actions
Given a high-impact tool call (register update, legal escalation), When it is dispatched, Then it is held as pending and runs only after a named human approves it; the workflow cannot approve its own request, and a decision can be made only once.

## SPEC-006 Redacted audit trail
Given any request, When audit events and traces are written, Then personal data (emails, phone numbers, card/SSN-like numbers, secrets) is redacted and every event carries the request's trace id.

## SPEC-007 Tracing
Given any request, When it completes, Then a trace with a unique id and timed spans is recorded.

## SPEC-008 Protected approval endpoint
Given the HTTP API, When the approval endpoint is called, Then it is disabled unless an approver token is configured, rejects wrong tokens, and accepts only the correct token with a named approver.

## SPEC-009 Quality gate
Given the golden question set and labelled documents, When evaluation runs, Then metrics are computed from real runs and the gate fails if any metric misses its threshold or any high-impact action executes without approval.

## SPEC-010 Optional LLM with citation guard
Given an LLM provider is enabled, When it returns text that lacks citations or cites unknown sources, Then the extractive answer is used instead; the LLM is off by default and is never called by tests or the demo.

## SPEC-011 MCP exposes only safe capabilities
Given the MCP server, When its tools are listed, Then only read-only/low-risk tools are exposed and no approval capability exists.

## SPEC-012 Cloud store with atomic single-use approvals
Given the DynamoDB-backed store, When audit events, traces and approvals are written, Then the same workflow behaves as with files, and an approval can be decided exactly once even if two decisions race (the second is refused).

## SPEC-013 Serverless entry point fails closed and leaks nothing
Given the Lambda handler behind an API, When a request arrives, Then only /health is open; other routes need the API key, the decision route also needs the approver token; an unconfigured secret disables the route (503); validation errors never echo the rejected input; responses carry security headers.

## SPEC-014 Safe, reversible cloud deployment
Given the deployment script, When it is run, Then plan mode prints resources and a cost estimate without calling AWS, apply needs an explicit profile and approval flag, creates only the opsbridge-live resources with least-privilege settings and no secrets in the function environment, rolls back everything if any step fails, and destroy removes everything and is safe to repeat.

## SPEC-015 Cost caps for live LLM calls
Given live Bedrock calls on a Free-plan account, When the demo runs, Then it refuses unless the plan is FREE/ACTIVE with credits, never exceeds a hard cap on paid calls, makes no paid call for questions it abstains on, and reports real token usage.
