from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

_ALLOWED_GRAINS = {"10m", "15m", "30m", "hour", "day"}
_ALLOWED_ROUTES = {"station_flow_day"}


@dataclass(frozen=True)
class SourceRegistration:
    logical_dataset: str
    city: str
    dataset_role: str
    source_version: str
    physical_mapping_ref: str
    physical_mapping_version: str
    physical_mapping_hash: str
    time_grain: str
    timezone: str
    status: str
    quality_status: str
    semantic_status: str
    quality_gate: str
    access_policy: str
    default_start: datetime
    default_end: datetime


def load_source_registration(
    path: Path,
    *,
    logical_dataset: str,
    city: str,
    source_version: str,
) -> SourceRegistration:
    payload = _read_object(path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("source registry has unsupported schema_version")
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise ValueError("source registry sources must be a list")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("logical_dataset") == logical_dataset
        and row.get("city") == city
        and row.get("source_version") == source_version
        and row.get("dataset_role") == "actual"
    ]
    if len(matches) != 1:
        raise ValueError("source registry must contain exactly one matching actual source")
    registration = _validated_registration(matches[0])
    from metro_agent.database import STATION_FLOW_MAPPING_VERSION, station_flow_mapping_hash

    implementation_hash = station_flow_mapping_hash()
    if registration.physical_mapping_version != STATION_FLOW_MAPPING_VERSION:
        raise ValueError("source registry physical mapping version does not match the adapter")
    if registration.physical_mapping_hash != implementation_hash:
        raise ValueError("source registry physical mapping hash does not match the adapter")
    return replace(registration, physical_mapping_hash=implementation_hash)


@dataclass(frozen=True)
class LogicalDataProduct:
    registry_version: str
    registry_hash: str
    logical_dataset: str
    dataset_role: str
    metric_ids: tuple[str, ...]
    dimensions: tuple[str, ...]
    time_basis: str
    timezone: str
    cross_midnight_policy: str
    quality_gate_id: str
    access_policy_id: str


def load_logical_data_product(path: Path, logical_dataset: str) -> LogicalDataProduct:
    payload = _read_object(path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("logical registry has unsupported schema_version")
    if set(payload) != {"schema_version", "registry_version", "products"}:
        raise ValueError("logical registry fields do not match the contract")
    products = payload.get("products")
    matches = (
        [
            item
            for item in products
            if isinstance(item, dict) and item.get("logical_dataset") == logical_dataset
        ]
        if isinstance(products, list)
        else []
    )
    if len(matches) != 1:
        raise ValueError("logical registry must contain exactly one matching data product")
    row = matches[0]
    required = {
        "logical_dataset",
        "dataset_role",
        "metric_ids",
        "dimensions",
        "time_basis",
        "timezone",
        "cross_midnight_policy",
        "quality_gate_id",
        "access_policy_id",
        "source_version_policy",
    }
    if set(row) != required or row.get("source_version_policy") != "immutable-only":
        raise ValueError("logical data product fields do not match the contract")
    if row.get("dataset_role") != "actual" or row.get("time_basis") != "event_time":
        raise ValueError("logical station-flow product semantics are unsupported")
    if row.get("timezone") != "Asia/Shanghai" or row.get("cross_midnight_policy") != "reject":
        raise ValueError("logical station-flow time policy is unsupported")
    metrics = row.get("metric_ids")
    dimensions = row.get("dimensions")
    if (
        not isinstance(metrics, list)
        or not metrics
        or not all(isinstance(item, str) for item in metrics)
    ):
        raise ValueError("logical data product metric_ids are invalid")
    if (
        not isinstance(dimensions, list)
        or not dimensions
        or not all(isinstance(item, str) for item in dimensions)
    ):
        raise ValueError("logical data product dimensions are invalid")
    return LogicalDataProduct(
        registry_version=str(payload["registry_version"]),
        registry_hash=_canonical_hash(payload),
        logical_dataset=logical_dataset,
        dataset_role="actual",
        metric_ids=tuple(metrics),
        dimensions=tuple(dimensions),
        time_basis="event_time",
        timezone="Asia/Shanghai",
        cross_midnight_policy="reject",
        quality_gate_id=str(row["quality_gate_id"]),
        access_policy_id=str(row["access_policy_id"]),
    )


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("source registry path must be an existing file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source registry cannot be read") from exc
    if not isinstance(payload, dict):
        raise ValueError("source registry root must be an object")
    return payload


def _validated_registration(row: dict[str, Any]) -> SourceRegistration:
    required = {
        "logical_dataset",
        "city",
        "dataset_role",
        "source_version",
        "physical_mapping_ref",
        "physical_mapping_version",
        "physical_mapping_hash",
        "time_grain",
        "timezone",
        "status",
        "quality_status",
        "semantic_status",
        "quality_gate",
        "access_policy",
        "default_time_range",
    }
    if set(row) != required:
        raise ValueError("source registry entry fields do not match the contract")
    string_fields = required - {"default_time_range"}
    if any(not isinstance(row[field], str) or not row[field].strip() for field in string_fields):
        raise ValueError("source registry string fields must be non-empty")
    if row["status"] != "approved":
        raise ValueError("source registry entry is not approved")
    if row["quality_status"] != "pass":
        raise ValueError("source registry quality gate did not pass")
    if row["semantic_status"] not in {"verified", "unverified"}:
        raise ValueError("source registry semantic status is unsupported")
    if row["physical_mapping_ref"] not in _ALLOWED_ROUTES:
        raise ValueError("source registry physical mapping is not allowlisted")
    if row["time_grain"] not in _ALLOWED_GRAINS:
        raise ValueError("source registry time grain is unsupported")
    if row["timezone"] != "Asia/Shanghai":
        raise ValueError("source registry timezone is unsupported")
    if re.search(r"(?:^|[-_])(current|latest)(?:$|[-_])", row["source_version"], re.IGNORECASE):
        raise ValueError("source registry requires an immutable source_version")
    time_range = row["default_time_range"]
    if not isinstance(time_range, dict) or set(time_range) != {"start", "end"}:
        raise ValueError("source registry default_time_range is invalid")
    start = _aware_datetime(time_range["start"], "start")
    end = _aware_datetime(time_range["end"], "end")
    if start >= end:
        raise ValueError("source registry default time range is not ordered")
    return SourceRegistration(
        logical_dataset=row["logical_dataset"],
        city=row["city"],
        dataset_role=row["dataset_role"],
        source_version=row["source_version"],
        physical_mapping_ref=row["physical_mapping_ref"],
        physical_mapping_version=row["physical_mapping_version"],
        physical_mapping_hash=row["physical_mapping_hash"],
        time_grain=row["time_grain"],
        timezone=row["timezone"],
        status=row["status"],
        quality_status=row["quality_status"],
        semantic_status=row["semantic_status"],
        quality_gate=row["quality_gate"],
        access_policy=row["access_policy"],
        default_start=start,
        default_end=end,
    )


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"source registry {label} must be a datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"source registry {label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"source registry {label} must include timezone")
    return parsed


def _canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
