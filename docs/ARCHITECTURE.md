# Architecture and design decisions

## Components
| Module | Responsibility |
|---|---|
| `retrieval.py` | Chunk the knowledge base by heading; BM25 ranking; idf-weighted **coverage** score |
| `answer.py` | Ask flow: retrieve, abstain below the coverage threshold, extractive answer with citations, optional LLM with citation guard |
| `classify.py` | Keyword classification with margin, header/regex extraction, confidence, instruction-text detection |
| `workflow.py` | Process a document: classify, extract, route (auto/review), plan tool calls deterministically, dispatch |
| `tools.py` | Allow-list, Pydantic schemas, impact levels, approvals store, mock integrations |
| `audit.py`, `redact.py`, `tracing.py` | Redacted append-only audit log, PII/secret redaction, trace ids and spans |
| `providers.py` | Extractive (default) and Bedrock providers |
| `api.py`, `cli.py`, `mcp_server.py` | Three interfaces over the same core |
| `evaluate.py` | Metrics and quality gate |

## Key decisions (ADR style)
1. **Deterministic core, LLM optional.** Reproducible tests and a free demo; an LLM can be added behind the same interface. *Trade-off:* extractive answers read less naturally.
2. **Abstention by coverage.** `coverage = idf-weighted share of question terms found in the best chunk`; below 0.30 -> abstain. Interpretable and debuggable; weak for paraphrases that share no words (a vector retriever would help).
3. **Planner is a fixed table, not model output.** Which tools run depends only on document type and extracted fields, so injected text cannot add actions.
4. **Approval is structural.** High-impact tools can only run via `tools.decide` by a named human; there is no code path from the workflow to execution of a high-impact tool.
5. **Review queue over guessing.** Low confidence or suspicious text stops automation; cost of a false stop is a human minute, cost of a false action is higher.
6. **Redact at write time.** Every audit/trace/tool record passes through `redact()`.
7. **MCP is read-only.** An AI client can ask and classify; it cannot approve.

## Failure paths
- Unknown tool / invalid arguments -> refused and audited, nothing runs.
- Tool exception -> the span is marked `error` and the exception propagates (no silent success).
- LLM output without valid citations -> extractive fallback, audited as `llm_guard_fallback`.
- Approval endpoint without a configured token -> 503; wrong token -> 401; already decided -> 409.

## Data flow for a document
`text -> classify (type, score, margin) -> extract -> confidence -> route`; `auto` -> `plan_actions` -> `dispatch` per call (allow-list, schema, impact) -> low impact executes / high impact pending -> audit + trace.
