"""Central settings. Everything is overridable by environment variables so tests and demos never touch real data."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = Path(os.environ.get("OPSBRIDGE_KB", ROOT / "data" / "kb"))
INBOX_DIR = ROOT / "data" / "inbox"
EVAL_DIR = ROOT / "data" / "eval"

TOP_K = 3
# Abstain when the best chunk covers less than this share of the question terms (idf-weighted). Chosen as the midpoint of the observed gap
# between the highest unanswerable (0.17) and lowest answerable (0.41) coverage on the small dev set; the real-world gap may be narrower.
ABSTAIN_THRESHOLD = float(os.environ.get("OPSBRIDGE_ABSTAIN_THRESHOLD", "0.30"))
# Documents below this extraction confidence go to human review instead of automatic routing.
AUTO_ROUTE_CONFIDENCE = float(os.environ.get("OPSBRIDGE_AUTO_ROUTE_CONFIDENCE", "0.75"))

# AWS defaults (Bedrock is OFF unless OPSBRIDGE_LLM=bedrock; nothing in this repo calls AWS by default).
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")


def runs_dir() -> Path:
    """Where traces, audit events, tickets and approvals are written (git-ignored)."""
    p = Path(os.environ.get("OPSBRIDGE_RUNS", ROOT / "runs"))
    p.mkdir(parents=True, exist_ok=True)
    return p
