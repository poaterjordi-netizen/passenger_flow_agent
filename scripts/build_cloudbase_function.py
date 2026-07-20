#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "infra" / "cloudbase" / "functions" / "metroAgentApi"
DEFAULT_TARGET = ROOT / "artifacts" / "cloudbase-function" / "metroAgentApi"
PACKAGE_FILES = (
    Path("__init__.py"),
    Path("contracts.py"),
    Path("query_engine.py"),
    Path("api/__init__.py"),
    Path("api/models.py"),
    Path("api/service.py"),
    Path("api/settings.py"),
)
DATA_FILES = ("metrics.json", "passenger_flow.csv")


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def build(target: Path, *, install_dependencies: bool = True) -> Path:
    target = target.resolve()
    if target == ROOT or ROOT not in target.parents:
        raise ValueError("CloudBase artifact target must stay inside the repository")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(SOURCE, target)
    for relative_path in PACKAGE_FILES:
        destination = target / "metro_agent" / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src" / "metro_agent" / relative_path, destination)
    data_target = target / "examples" / "synthetic_data"
    data_target.mkdir(parents=True, exist_ok=True)
    for filename in DATA_FILES:
        shutil.copy2(ROOT / "examples" / "synthetic_data" / filename, data_target / filename)

    if install_dependencies:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-compile",
                "--only-binary=:all:",
                "--platform=manylinux2014_x86_64",
                "--implementation=cp",
                "--python-version=3.11",
                "--target",
                str(target),
                "--requirement",
                str(SOURCE / "requirements.txt"),
            ],
            check=True,
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the isolated CloudBase function bundle")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--skip-dependencies", action="store_true")
    args = parser.parse_args()
    target = build(args.target, install_dependencies=not args.skip_dependencies)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
