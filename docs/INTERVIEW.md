# Interview talking points (answer frameworks, adapt to what you have done)

## 60-second pitch
"I built OpsBridge AI to show how I would deliver an AI automation for policy and content operations. It turns request emails into classified, validated tickets, answers policy questions only with citations or says it doesn't know, and holds every high-impact action for a named human approver. It has 57 tests, a quality gate with real metrics, redacted audit logs and traces. The data is synthetic and it isn't deployed; I'm explicit about that. What I want to show is the discipline: acceptance criteria first, controls built in, measured quality, honest limits."

## Technical questions
1. **Why abstain, and how did you set the threshold?** Wrong answers cost more than "I don't know". Coverage is the idf-weighted share of question terms found in the best chunk. On my small set out-of-scope questions peaked at 0.17 and valid ones started at 0.41, so I used 0.30 (the midpoint). My first guess of 0.45 wrongly abstained on 2 of 18 valid questions. The gap on real data will be narrower, so I'd recalibrate on real traffic.
2. **How do you stop prompt injection?** Documents are data. The planner is a fixed table keyed by document type; text inside a document can't add tools. Instruction-like text routes to human review. High-impact tools can't run without a human decision. For LLM answers, sources are delimited as data and the output must cite known sources or it is discarded.
3. **Why not a vector database?** A deterministic lexical baseline made tests and evaluation reproducible and free. It is a known limitation for paraphrase; the Retriever interface is where Chroma/pgvector/OpenSearch fit, and I'd compare them on recall@k and cost before choosing.
4. **How would you evaluate with an LLM in the loop?** Same golden sets plus LLM-judge metrics such as Ragas (faithfulness, answer relevancy, context precision/recall), calibrated against human labels, run in CI as a gate. I haven't run Ragas yet.
5. **What does tracing give you?** One id per request across spans (retrieve, classify, tool), with durations and errors; I'd export to OpenTelemetry/Langfuse so quality, latency and cost can be viewed per workflow.
6. **How is the API secured?** The approval endpoint is off unless a token is configured, compares in constant time, needs a named approver. In production it sits behind the identity provider; I treat the token as a minimal local control.

## Delivery-management questions
1. **How did you define "done"?** Specs with Given/When/Then, each linked to tests, plus a metric gate. A spec without a test fails the build.
2. **What are the main risks and mitigations?** Wrong automation (review queue, approvals), data leakage (redaction, synthetic data, no default cloud calls), cost (offline default, Bedrock only after review), over-claiming (limits listed in README).
3. **How would you roll this out?** Shadow mode comparing proposals to human decisions, then assisted mode for low-impact actions, then selective automation, with the acceptance gate re-run on each change and a rollback path.
4. **How do you handle a stakeholder who wants full automation?** Show the measured error and review rates, propose tiered autonomy by impact, agree who owns approvals, and set review-rate and accuracy targets.
5. **What would you measure after launch?** Automation rate, review rate, correction rate, time to ticket, abstention rate, approval turnaround, audit completeness, cost per request.
6. **What would you not claim?** Production accuracy, business savings, or production deployment: none is evidenced here.
