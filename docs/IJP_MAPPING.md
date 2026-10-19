# Mapping to the IJP: Technical Delivery Manager - AI (BPA / DPA)

Status words: **Verified** = implemented and covered by a passing test or evaluation in this repo; **Partial** = some of it; **Not covered** = no implementation here.

| IJP item | Evidence in this repo | Status |
|---|---|---|
| Lead automation of manual-intensive workflows (R1, R2, K2) | Request intake automation: classify, extract, route, ticket (`workflow.py`, `data/inbox`) | Partial (prototype, synthetic data; leading a team is not shown by code) |
| Oversee design to deployment, AI-first (R3) | Architecture doc, specs, tests, CI definition, quality gate; short-lived live deployment on AWS with Free-plan guard, rollback and verified teardown | Partial (demo deployment, not production) |
| Technical direction using AI/GenAI (R4, K4) | ADR-style decisions in `docs/ARCHITECTURE.md` with trade-offs | Partial |
| Integration into application suites, scalability, minimal disruption (R5, K6) | HTTP API, MCP server, mock tool layer with stable schemas | Partial (mock integrations) |
| Spec-driven development (summary) | `specs/SPECS.md` with acceptance criteria; every spec linked to tests; generated traceability | Verified |
| Python (K3a) | 7 source modules, 79 tests | Verified |
| Prompt engineering (K3c) | Bedrock provider prompt: sources as data, cite-or-INSUFFICIENT rule (tested with a stub) | Partial (LLM not exercised live) |
| LLM architecture: embeddings, context windows (K3b) | Context handling via retrieval and prompt budget; **no embeddings** | Partial |
| LangChain/LangGraph or equivalents (K3d) | Own lightweight orchestration; no framework | Not covered |
| RAG and vector databases (K3e) | Lexical RAG with citations and abstention; **no vector DB** | Partial |
| Agent and tool-calling, MCP (K3f) | Allow-listed validated tool calls, approval gate, MCP server | Verified (mock tools) |
| Evaluation frameworks / Ragas (K3g) | Custom deterministic harness with a quality gate and failure cases; **not Ragas** | Partial |
| LLMOps and tracing, Langfuse/Arize (K3h) | Local trace ids and spans, redacted audit; no Langfuse/Arize | Partial |
| Cloud AI services: Bedrock/Vertex/Azure OpenAI (K3i) | Bedrock provider (ap-southeast-2) implemented and stub-tested; a live call reached Bedrock but was refused with a daily-token quota message; separately the app ran live on AWS (Lambda, API Gateway, DynamoDB, SSM) and was torn down | Partial |
| Security / governance / responsible AI | Redaction, approval gate, review queue, injection handling, protected approval API | Verified (in scope of the prototype) |
| Stakeholder management, negotiation, leadership (R6-R8, K5, K7) | Not demonstrable by code | Not covered (use real STAR stories) |
| 12+ years IT, 4+ years delivering AI (K1) | Not demonstrable by code | Not covered |

## Delivery-management artefacts in this repo
- Acceptance criteria and traceability: `specs/SPECS.md`, `docs/TRACEABILITY.md`
- Measurable quality gate and threshold rationale: `docs/EVALUATION.md`
- Risk and control thinking: README security section, `docs/ARCHITECTURE.md` failure paths
- Operational readiness: CI workflow, audit and trace outputs, runbook-style CLI

## Honest scope
This is a prototype on synthetic data. It shows design, control and evaluation discipline. It is not evidence of production delivery, business outcomes, or team leadership.
