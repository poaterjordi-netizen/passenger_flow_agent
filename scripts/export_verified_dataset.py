#!/usr/bin/env python3
"""Export the four future-training datasets from governed eligible trajectories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from metro_agent.assistant.dataset_export import export_verified_trajectories


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_verified_trajectories(args.run_dir, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
