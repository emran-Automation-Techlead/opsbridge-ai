# OpsBridge live on Amazon Bedrock - plan and approval sheet

**Status: PLAN. No Bedrock call has been made.** (Region note: the Free-plan account is locked to Sydney, ap-southeast-2; Mumbai was refused. The first live call in Mumbai was also answered with 'your account is currently being verified', which AWS says normally takes under 2 hours.)

## What the demo shows
`python demo/live_bedrock.py --profile portfolio-readonly --yes-i-approved-the-cost` runs six policy questions through the real OpsBridge pipeline with a real Amazon Bedrock model in Sydney (`ap-southeast-2`):
- retrieval picks the policy chunks (local, free);
- if there is no evidence the system abstains and makes **no paid call**;
- otherwise the model rephrases only the retrieved, redacted text and must cite sources as [n]; uncited or unknown-source answers are discarded and the extractive answer is used (SPEC-010);
- real token counts and latency are printed; evidence is saved to `docs/bedrock_live_run.txt`.

## Model
`amazon.nova-lite-v1:0` (on-demand, listed as ACTIVE in ap-southeast-2 on 2026-10-20): Amazon Nova Lite: small and cheap, supports the Converse API. Not verified: that your account may invoke it (the organisation policy might deny Bedrock invocation, or model access might need enabling). The first call tells us; a denial costs nothing.

## Cost (estimate - verify in the Billing console)
About 4 paid calls x (roughly 350 input + up to 300 output tokens). At an **assumed** USD 0.06 / 0.24 per million tokens that is **about USD 0.001**; the hard cap of 10 calls bounds the worst case at **under USD 0.01**, even if real prices were 10x higher. It is drawn from your USD 120 Free-plan credits; the script refuses to run unless the account is FREE/ACTIVE with credits (tested). Questions that abstain make no call.

## Permission needed (one statement)
`deploy/bedrock-demo-policy.json` (also included in the combined `deploy/deployer-policy.json`): `bedrock:InvokeModel` on that one model ARN in ap-southeast-2 only. No other service, no other model, no write access to anything. Update the existing managed policy `opsbridge-live-deployer` with the combined JSON (it is already attached to `portfolio-readonly`), delete the old Mumbai inline policy `opsbridge-bedrock-demo`, and detach/delete the policy when finished.

## Rollback
Nothing is created. Rollback = detach the policy. Billing check: Billing > Bills / Cost Explorer after 24 hours.

## Explore AWS reward (separate, your call)
Your account lists "Use a foundation model in the Amazon Bedrock playground" (USD 20 credit, NOT_STARTED). Using the console Playground once would complete it if the console confirms; this repo's script does not count.
