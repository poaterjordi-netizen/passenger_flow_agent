from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_agent.assistant.failure_analysis import summarize_failure_traces


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cluster assistant run failures into regression-test candidates."
    )
    parser.add_argument("trace_root", type=Path, help="Assistant trace root or runs directory")
    parser.add_argument("--output", type=Path, help="Optional local JSON report path")
    args = parser.parse_args()
    report = summarize_failure_traces(args.trace_root.resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.resolve().write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
