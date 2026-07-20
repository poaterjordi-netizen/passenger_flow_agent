from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_DIMENSIONS = {"line", "station", "direction", "time"}
ALLOWED_FILTER_FIELDS = {"line_id", "station_id", "direction"}
ALLOWED_OPERATORS = {"eq", "in"}
REQUIRED_DATA_FIELDS = {
    "timestamp", "line_id", "station_id", "direction", "entries", "exits", "transfers"
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def _parse_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label}: must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label}: must include timezone")
    return parsed


def validate_metric_registry(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("metric registry: unsupported schema_version")
    rows = payload.get("metrics")
    if not isinstance(rows, list) or not rows:
        raise ValueError("metric registry: metrics must be a non-empty list")
    registry: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("metric registry: every metric needs a string id")
        metric_id = row["id"]
        if metric_id in registry:
            raise ValueError(f"metric registry: duplicate id {metric_id}")
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, list) or not set(dimensions) <= ALLOWED_DIMENSIONS:
            raise ValueError(f"metric registry: invalid dimensions for {metric_id}")
        if not isinstance(row.get("source_fields"), list) or not row["source_fields"]:
            raise ValueError(f"metric registry: source_fields missing for {metric_id}")
        registry[metric_id] = row
    return registry


def validate_query_ir(query: Any, registry: dict[str, dict[str, Any]], label: str) -> None:
    if not isinstance(query, dict):
        raise ValueError(f"{label}: query_ir must be an object")
    required = {"metric", "time_range", "dimensions", "filters", "limit"}
    if set(query) != required:
        raise ValueError(f"{label}: query_ir fields must be exactly {sorted(required)}")
    metric = query["metric"]
    if metric not in registry:
        raise ValueError(f"{label}: unknown metric {metric}")
    time_range = query["time_range"]
    if not isinstance(time_range, dict) or set(time_range) != {"start", "end"}:
        raise ValueError(f"{label}: invalid time_range")
    start = _parse_datetime(time_range["start"], f"{label}.start")
    end = _parse_datetime(time_range["end"], f"{label}.end")
    if start >= end:
        raise ValueError(f"{label}: start must be before end")
    dimensions = query["dimensions"]
    if not isinstance(dimensions, list) or len(dimensions) != len(set(dimensions)):
        raise ValueError(f"{label}: dimensions must be a unique list")
    if not set(dimensions) <= set(registry[metric]["dimensions"]):
        raise ValueError(f"{label}: dimension not allowed for metric {metric}")
    filters = query["filters"]
    if not isinstance(filters, list):
        raise ValueError(f"{label}: filters must be a list")
    for item in filters:
        if not isinstance(item, dict) or set(item) != {"field", "operator", "value"}:
            raise ValueError(f"{label}: invalid filter shape")
        if item["field"] not in ALLOWED_FILTER_FIELDS or item["operator"] not in ALLOWED_OPERATORS:
            raise ValueError(f"{label}: filter is not allowlisted")
        if item["operator"] == "in" and not isinstance(item["value"], list):
            raise ValueError(f"{label}: 'in' filter value must be a list")
    limit = query["limit"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError(f"{label}: limit must be an integer from 1 to 1000")


def validate_gold_cases(path: Path, registry: dict[str, dict[str, Any]]) -> int:
    payload = _read_json(path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("gold cases: unsupported schema_version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("gold cases: cases must be a non-empty list")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("gold cases: every case must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise ValueError(f"gold cases: invalid or duplicate case_id {case_id}")
        seen.add(case_id)
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError(f"{case_id}: question is required")
        validate_query_ir(case.get("query_ir"), registry, case_id)
        expected = case.get("expected")
        if not isinstance(expected, dict) or expected.get("status") not in {"answer", "clarify", "reject"}:
            raise ValueError(f"{case_id}: invalid expected status")
        if not isinstance(case.get("risk_tags"), list):
            raise ValueError(f"{case_id}: risk_tags must be a list")
    return len(cases)


def validate_passenger_flow_csv(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or []) != REQUIRED_DATA_FIELDS:
            raise ValueError(f"data: fields must be exactly {sorted(REQUIRED_DATA_FIELDS)}")
        seen: set[tuple[str, str, str, str]] = set()
        count = 0
        for line_number, row in enumerate(reader, start=2):
            _parse_datetime(row["timestamp"], f"data line {line_number}.timestamp")
            if row["direction"] not in {"up", "down", "na"}:
                raise ValueError(f"data line {line_number}: invalid direction")
            for field in ("entries", "exits", "transfers"):
                try:
                    value = int(row[field])
                except ValueError as exc:
                    raise ValueError(f"data line {line_number}: {field} must be an integer") from exc
                if value < 0:
                    raise ValueError(f"data line {line_number}: {field} must be non-negative")
            key = (row["timestamp"], row["line_id"], row["station_id"], row["direction"])
            if key in seen:
                raise ValueError(f"data line {line_number}: duplicate observation key")
            seen.add(key)
            count += 1
    if count == 0:
        raise ValueError("data: at least one row is required")
    return count


def validate_repository_contracts(metrics: Path, gold_cases: Path, data: Path) -> dict[str, int]:
    registry = validate_metric_registry(metrics)
    return {
        "metrics": len(registry),
        "gold_cases": validate_gold_cases(gold_cases, registry),
        "data_rows": validate_passenger_flow_csv(data),
    }
