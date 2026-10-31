# Project plan: capabilities demonstrated

Status words: **Verified** = implemented and covered by a passing test or evaluation in this repo; **Partial** = some of it; **Not covered** = no implementation here.

| Capability area | Evidence in this repo | Status |
|---|---|---|
| Lead automation of manual-intensive workflows | Request intake automation: classify, extract, route, ticket (`workflow.py`, `data/inbox`) | Partial (prototype, synthetic data; leading a team is not shown by code) |
| Oversee design to deployment, AI-first | Architecture doc, specs, tests, CI definition, quality gate; short-lived live deployment on AWS with Free-plan guard, rollback and verified teardown | Partial (demo deployment, not production) |
| Technical direction using AI/GenAI | ADR-style decisions in `docs/ARCHITECTURE.md` with trade-offs | Partial |
| Integration into application suites, scalability, minimal disruption | HTTP API, MCP server, mock tool layer with stable schemas | Partial (mock integrations) |
| Spec-driven development | `specs/SPECS.md` with acceptance criteria; every spec linked to tests; generated traceability | Verified |
| Python | 7 source modules, 79 tests | Verified |
| Prompt engineering | Bedrock provider prompt: sources as data, cite-or-INSUFFICIENT rule (tested with a stub) | Partial (LLM not exercised live) |
| LLM architecture: embeddings, context windows | Context handling via retrieval and prompt budget; no embeddings | Partial |
| LangChain/LangGraph or equivalents | Own lightweight orchestration; no framework | Not covered |
| RAG and vector databases | Lexical RAG with citations and abstention; no vector DB | Partial |
| Agent and tool-calling, MCP | Allow-listed validated tool calls, approval gate, MCP server | Verified (mock tools) |
| Evaluation frameworks / Ragas | Custom deterministic harness with a quality gate and failure cases; not Ragas | Partial |
| LLMOps and tracing, Langfuse/Arize | Local trace ids and spans, redacted audit; no Langfuse/Arize | Partial |
| Cloud AI services: Bedrock/Vertex/Azure OpenAI | Bedrock provider (ap-southeast-2) implemented and stub-tested; a live call reached Bedrock but was refused with a daily-token quota message; separately the app ran live on AWS (Lambda, API Gateway, DynamoDB, SSM) and was torn down | Partial |
| Security / governance / responsible AI | Redaction, approval gate, review queue, injection handling, protected approval API | Verified (in scope of the prototype) |
| Stakeholder management, negotiation, leadership | Not demonstrable by code | Not covered (use real examples) |
| Years of IT and AI delivery experience | Not demonstrable by code | Not covered |

## Delivery-management artefacts in this repo

- Acceptance criteria and traceability: `specs/SPECS.md`, `docs/TRACEABILITY.md`
- Measurable quality gate and threshold rationale: `docs/EVALUATION.md`
- Risk and control thinking: README security section, `docs/ARCHITECTURE.md` failure paths
- Operational readiness: CI workflow, audit and trace outputs, runbook-style CLI

## Honest scope

This is a prototype on synthetic data. It shows design, control and evaluation discipline. It is not evidence of production delivery, business outcomes, or team leadership.
