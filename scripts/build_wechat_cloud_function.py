#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "infra" / "cloudbase" / "functions" / "metroAgentApi-nodejs"
DEFAULT_TARGET = ROOT / "clients" / "wechat-miniprogram" / "cloudfunctions" / "metroAgentApi"
DATA_FILES = ("metrics.json", "passenger_flow.csv")


def build(target: Path) -> Path:
    target = target.resolve()
    if target == ROOT or ROOT not in target.parents:
        raise ValueError("WeChat cloud function artifact must stay inside the repository")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE,
        target,
        ignore=shutil.ignore_patterns("node_modules", ".DS_Store"),
    )
    for filename in DATA_FILES:
        shutil.copy2(ROOT / "examples" / "synthetic_data" / filename, target / filename)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the synthetic Node.js function for WeChat Cloud Development"
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    print(build(args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
