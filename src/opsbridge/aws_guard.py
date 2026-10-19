"""Safety checks before any paid AWS call from the demo scripts."""
from __future__ import annotations

MIN_CREDITS_USD = 20.0


def check_free_plan(session) -> float:
    """Return remaining credits if the account is on the FREE plan (usage paid from credits, never billed); otherwise raise.
    Uses the read-only Free Tier API. There is deliberately no way to skip this from the command line."""
    state = session.client("freetier", region_name="us-east-1").get_account_plan_state()
    plan, status = state.get("accountPlanType"), state.get("accountPlanStatus")
    credits = float((state.get("accountPlanRemainingCredits") or {}).get("amount", 0))
    if plan != "FREE" or status != "ACTIVE":
        raise RuntimeError(f"account plan is {plan}/{status}, not FREE/ACTIVE: refusing to make paid calls")
    if credits < MIN_CREDITS_USD:
        raise RuntimeError(f"only USD {credits:.2f} of credits left (minimum {MIN_CREDITS_USD:.0f}): refusing to make paid calls")
    return credits
