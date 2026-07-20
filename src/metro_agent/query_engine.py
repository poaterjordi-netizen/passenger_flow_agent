from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metro_agent.contracts import (
    validate_gold_cases,
    validate_metric_registry,
    validate_passenger_flow_csv,
    validate_query_ir,
)

DIMENSION_COLUMNS = {
    "line": "line_id",
    "station": "station_id",
    "direction": "direction",
    "time": "timestamp",
}
FILTER_COLUMNS = {"line_id", "station_id", "direction"}
SAFE_METRIC_EXPRESSIONS = {
    ("sum", ("entries",)): "SUM(entries)",
    ("sum", ("exits",)): "SUM(exits)",
    ("sum", ("transfers",)): "SUM(transfers)",
    ("sum_difference", ("entries", "exits")): "SUM(entries) - SUM(exits)",
}
BLOCKED_RISK_TAGS = {"credential_access", "privacy", "production_write", "scope_escalation"}


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    parameters: tuple[Any, ...]
    output_columns: tuple[str, ...]
    metric: str
    dimensions: tuple[str, ...]


def load_query_ir(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: root must be an object")
    return payload


def _metric_expression(metric_definition: dict[str, Any]) -> str:
    key = (
        metric_definition.get("aggregation"),
        tuple(metric_definition.get("source_fields", [])),
    )
    try:
        return SAFE_METRIC_EXPRESSIONS[key]
    except KeyError as exc:
        raise ValueError("metric registry: unsupported deterministic aggregation") from exc


def _compile_query(query: dict[str, Any], registry: dict[str, dict[str, Any]]) -> QueryPlan:
    validate_query_ir(query, registry, "query")
    metric = query["metric"]
    dimensions = tuple(query["dimensions"])
    selected_dimensions = [
        f'{DIMENSION_COLUMNS[dimension]} AS "{dimension}"' for dimension in dimensions
    ]
    select_items = [*selected_dimensions, f'{_metric_expression(registry[metric])} AS "{metric}"']

    start = datetime.fromisoformat(query["time_range"]["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(query["time_range"]["end"].replace("Z", "+00:00"))
    predicates = ["timestamp_epoch >= ?", "timestamp_epoch < ?"]
    parameters: list[Any] = [int(start.timestamp()), int(end.timestamp())]

    for item in query["filters"]:
        field = item["field"]
        if field not in FILTER_COLUMNS:  # Defense in depth after contract validation.
            raise ValueError(f"query: filter field is not allowlisted: {field}")
        if item["operator"] == "eq":
            predicates.append(f"{field} = ?")
            parameters.append(item["value"])
        elif item["operator"] == "in":
            values = item["value"]
            placeholders = ", ".join("?" for _ in values)
            predicates.append(f"{field} IN ({placeholders})")
            parameters.extend(values)
        else:  # Defense in depth after contract validation.
            raise ValueError(f"query: operator is not allowlisted: {item['operator']}")

    sql = f"SELECT {', '.join(select_items)} FROM passenger_flow"
    sql += f" WHERE {' AND '.join(predicates)}"
    if dimensions:
        group_columns = ", ".join(DIMENSION_COLUMNS[dimension] for dimension in dimensions)
        sql += f" GROUP BY {group_columns} ORDER BY {group_columns}"
    sql += " LIMIT ?"
    parameters.append(query["limit"])
    return QueryPlan(
        sql=sql,
        parameters=tuple(parameters),
        output_columns=(*dimensions, metric),
        metric=metric,
        dimensions=dimensions,
    )


def compile_query(metrics_path: Path, query: dict[str, Any]) -> QueryPlan:
    return _compile_query(query, validate_metric_registry(metrics_path))


def _open_synthetic_database(data_path: Path) -> sqlite3.Connection:
    validate_passenger_flow_csv(data_path)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE passenger_flow (
            timestamp TEXT NOT NULL,
            timestamp_epoch INTEGER NOT NULL,
            line_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('up', 'down', 'na')),
            entries INTEGER NOT NULL CHECK (entries >= 0),
            exits INTEGER NOT NULL CHECK (exits >= 0),
            transfers INTEGER NOT NULL CHECK (transfers >= 0),
            PRIMARY KEY (timestamp, line_id, station_id, direction)
        )
        """
    )
    with data_path.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            rows.append(
                (
                    row["timestamp"],
                    int(timestamp.timestamp()),
                    row["line_id"],
                    row["station_id"],
                    row["direction"],
                    int(row["entries"]),
                    int(row["exits"]),
                    int(row["transfers"]),
                )
            )
    connection.executemany(
        """
        INSERT INTO passenger_flow (
            timestamp, timestamp_epoch, line_id, station_id, direction,
            entries, exits, transfers
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return connection


def _audit_payload(
    query: dict[str, Any], plan: QueryPlan, result: dict[str, Any], data_path: Path
) -> dict[str, Any]:
    canonical_query = json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    query_fingerprint = hashlib.sha256(canonical_query.encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0",
        "audit_id": f"query-{query_fingerprint[:16]}",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "succeeded",
        "query_fingerprint": query_fingerprint,
        "query_ir": query,
        "metric": plan.metric,
        "dimensions": list(plan.dimensions),
        "sql_template": plan.sql,
        "parameter_count": len(plan.parameters),
        "data_source": data_path.name,
        "row_count": result["row_count"],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def execute_query(
    metrics_path: Path,
    data_path: Path,
    query: dict[str, Any],
    *,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    plan = compile_query(metrics_path, query)
    connection = _open_synthetic_database(data_path)
    try:
        cursor = connection.execute(plan.sql, plan.parameters)
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()
    result = {
        "status": "answer",
        "metric": plan.metric,
        "dimensions": list(plan.dimensions),
        "rows": rows,
        "row_count": len(rows),
    }
    if audit_path is not None:
        _write_json(audit_path, _audit_payload(query, plan, result, data_path))
    return result


def _actual_value(result: dict[str, Any]) -> Any:
    dimensions = result["dimensions"]
    metric = result["metric"]
    rows = result["rows"]
    if len(dimensions) == 1:
        dimension = dimensions[0]
        return {row[dimension]: row[metric] for row in rows}
    if not dimensions and len(rows) == 1:
        return rows[0][metric]
    return rows


def evaluate_gold_cases(
    metrics_path: Path, data_path: Path, gold_cases_path: Path
) -> dict[str, Any]:
    registry = validate_metric_registry(metrics_path)
    with gold_cases_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_gold_cases(gold_cases_path, registry)

    case_results = []
    for case in payload["cases"]:
        expected = case["expected"]
        blocked_tags = sorted(set(case["risk_tags"]) & BLOCKED_RISK_TAGS)
        if blocked_tags:
            actual_status = "reject"
            actual_value = None
            executed = False
            policy_reason = f"blocked risk tags: {', '.join(blocked_tags)}"
        else:
            query_result = execute_query(metrics_path, data_path, case["query_ir"])
            actual_status = query_result["status"]
            actual_value = _actual_value(query_result)
            executed = True
            policy_reason = None
        passed = actual_status == expected["status"]
        if expected["status"] == "answer":
            passed = passed and actual_value == expected.get("value")
        case_results.append(
            {
                "case_id": case["case_id"],
                "expected_status": expected["status"],
                "actual_status": actual_status,
                "expected_value": expected.get("value"),
                "actual_value": actual_value,
                "executed": executed,
                "policy_reason": policy_reason,
                "passed": passed,
            }
        )
    passed_count = sum(1 for case in case_results if case["passed"])
    return {
        "schema_version": "1.0",
        "summary": {
            "total": len(case_results),
            "passed": passed_count,
            "failed": len(case_results) - passed_count,
        },
        "cases": case_results,
    }


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    _write_json(path, payload)
