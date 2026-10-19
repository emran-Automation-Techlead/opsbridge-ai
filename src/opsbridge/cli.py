"""Command line: ask, process, approvals, eval. Examples:
  python -m opsbridge.cli ask "How long is published content kept?"
  python -m opsbridge.cli process data/inbox/D01.txt
  python -m opsbridge.cli approvals list
  python -m opsbridge.cli approvals decide <id> --approver "Dana Wu" --approve
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import answer, tools, workflow
from .providers import get_provider


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="opsbridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask"); a.add_argument("question")
    d = sub.add_parser("process"); d.add_argument("path")
    ap = sub.add_parser("approvals"); ap.add_argument("action", choices=["list", "decide"]); ap.add_argument("id", nargs="?")
    ap.add_argument("--approver"); g = ap.add_mutually_exclusive_group(); g.add_argument("--approve", action="store_true"); g.add_argument("--reject", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "ask":
        print(answer.ask(args.question, provider=get_provider(), actor="cli").model_dump_json(indent=2))
    elif args.cmd == "process":
        print(workflow.process_document(Path(args.path).read_text(encoding="utf-8"), actor="cli").model_dump_json(indent=2))
    else:
        if args.action == "list":
            print(json.dumps(tools.list_approvals(), indent=2))
        else:
            if not (args.id and args.approver and (args.approve or args.reject)):
                p.error("decide needs <id> --approver NAME and --approve or --reject")
            print(json.dumps(tools.decide(args.id, args.approver, args.approve), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
