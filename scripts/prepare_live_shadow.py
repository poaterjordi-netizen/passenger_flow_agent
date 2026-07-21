#!/usr/bin/env python3
"""Prepare a redacted, external source registration for local live shadow use."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from metro_agent.database import (
    STATION_FLOW_MAPPING_VERSION,
    DatabaseSettings,
    ReadOnlyMetroDatabase,
    station_flow_mapping_hash,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--time-grain", default="10m")
    return parser


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _flow_value(row: dict[str, Any], field: str) -> float:
    if field not in row or row[field] is None:
        raise ValueError(f"live source is missing required {field} values")
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"live source has a non-numeric {field} value")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"live source has an invalid {field} value")
    return parsed


def main() -> int:
    args = _parser().parse_args()
    if args.start.tzinfo is None or args.end.tzinfo is None or args.start >= args.end:
        raise ValueError("preflight range must be timezone-aware and ordered")
    if args.start.date() != (args.end.replace(microsecond=0)).date():
        raise ValueError("preflight range must remain within one local date")
    settings = DatabaseSettings.from_env()
    database = ReadOnlyMetroDatabase(settings)
    start = args.start.replace(tzinfo=None)
    end = args.end.replace(tzinfo=None)
    result = database.query_station_flow_day(
        date(args.start.year, args.start.month, args.start.day),
        start_time=start,
        end_time=end,
        limit=50_000,
    )
    if result.truncated:
        raise ValueError("live source preflight was truncated; narrow the configured range")
    if not result.rows:
        raise ValueError("live source preflight returned no rows")
    for row in result.rows:
        _flow_value(row, "InFlow")
        _flow_value(row, "OutFlow")
    event_times = sorted(
        row["StartTime"] for row in result.rows if isinstance(row.get("StartTime"), datetime)
    )
    if not event_times:
        raise ValueError("live source preflight found no valid event timestamps")
    mapping_hash = station_flow_mapping_hash()
    registry = {
        "schema_version": "1.0",
        "sources": [
            {
                "logical_dataset": "fact_station_flow_actual",
                "city": args.city,
                "dataset_role": "actual",
                "source_version": args.source_version,
                "physical_mapping_ref": "station_flow_day",
                "physical_mapping_version": STATION_FLOW_MAPPING_VERSION,
                "physical_mapping_hash": mapping_hash,
                "time_grain": args.time_grain,
                "timezone": "Asia/Shanghai",
                "status": "approved",
                "quality_status": "pass",
                "semantic_status": "unverified",
                "quality_gate": "station-flow-actual-quality-v1",
                "access_policy": "station-flow-aggregate-read-v1",
                "default_time_range": {
                    "start": args.start.isoformat(),
                    "end": args.end.isoformat(),
                },
            }
        ],
    }
    report = {
        "schema_version": "1.0",
        "status": "passed_for_local_live_shadow",
        "production_promotion": False,
        "source_version": args.source_version,
        "city_semantics": "unverified",
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "source_row_count": result.row_count,
        "truncated": result.truncated,
        "event_time_min": event_times[0].isoformat(),
        "event_time_max": event_times[-1].isoformat(),
        "required_flow_values_valid": True,
        "tls_cipher": result.tls_cipher,
        "tls_identity_mode": result.tls_identity_mode,
        "physical_mapping_version": STATION_FLOW_MAPPING_VERSION,
        "physical_mapping_hash": mapping_hash,
    }
    _atomic_private_json(args.registry, registry)
    _atomic_private_json(args.report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_row_count": result.row_count,
                "tls_identity_mode": result.tls_identity_mode,
                "registry": str(args.registry.resolve()),
                "report": str(args.report.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
