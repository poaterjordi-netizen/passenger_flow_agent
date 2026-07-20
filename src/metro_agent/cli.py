from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_agent.contracts import validate_repository_contracts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metro-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate P0 contracts and synthetic fixtures")
    validate.add_argument("--metrics", type=Path, required=True)
    validate.add_argument("--gold-cases", type=Path, required=True)
    validate.add_argument("--data", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "validate":
        summary = validate_repository_contracts(args.metrics, args.gold_cases, args.data)
        print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
