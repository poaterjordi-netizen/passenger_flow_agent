from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metro_agent.contracts import validate_repository_contracts
from metro_agent.query_engine import (
    evaluate_gold_cases,
    execute_query,
    load_query_ir,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metro-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate", help="validate P0 contracts and synthetic fixtures"
    )
    validate.add_argument("--metrics", type=Path, required=True)
    validate.add_argument("--gold-cases", type=Path, required=True)
    validate.add_argument("--data", type=Path, required=True)
    query = subparsers.add_parser("query", help="execute a validated QueryIR on synthetic data")
    query.add_argument("--metrics", type=Path, required=True)
    query.add_argument("--data", type=Path, required=True)
    query.add_argument("--query-ir", type=Path, required=True)
    query.add_argument("--audit", type=Path, required=True)
    evaluate = subparsers.add_parser("eval", help="run the deterministic P1 Gold Case suite")
    evaluate.add_argument("--metrics", type=Path, required=True)
    evaluate.add_argument("--data", type=Path, required=True)
    evaluate.add_argument("--gold-cases", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            summary = validate_repository_contracts(args.metrics, args.gold_cases, args.data)
            print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "query":
            result = execute_query(
                args.metrics,
                args.data,
                load_query_ir(args.query_ir),
                audit_path=args.audit,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "eval":
            report = evaluate_gold_cases(args.metrics, args.data, args.gold_cases)
            write_json_report(args.report, report)
            print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
            return 0 if report["summary"]["failed"] == 0 else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
