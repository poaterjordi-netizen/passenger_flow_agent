from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.settings import ApiSettings
from metro_agent.contracts import validate_metric_registry, validate_passenger_flow_csv
from metro_agent.query_engine import execute_query

_AUDIT_ID = re.compile(r"^(?:query|forecast)-[0-9a-f]{32}$")
_METRIC_LABELS = {
    "entries": "进站量",
    "exits": "出站量",
    "transfers": "换乘量",
    "net_inflow": "净流入",
}
_DIMENSION_LABELS = {
    "line": "线路",
    "station": "车站",
    "direction": "方向",
    "time": "时间",
}


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuditStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"query", "forecast"}:
            raise ValueError("unsupported audit operation")
        audit_id = f"{operation}-{uuid.uuid4().hex}"
        record = {
            "schema_version": "1.0",
            "audit_id": audit_id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "succeeded",
            "operation": operation,
            **payload,
        }
        target = self.directory / f"{audit_id}.json"
        temporary = self.directory / f".{audit_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def get(self, audit_id: str) -> dict[str, Any]:
        if not _AUDIT_ID.fullmatch(audit_id):
            raise ValueError("invalid audit id")
        path = self.directory / f"{audit_id}.json"
        if not path.is_file():
            raise FileNotFoundError(audit_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("audit_id") != audit_id:
            raise ValueError("invalid audit record")
        return payload


def _audit_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": record["audit_id"],
        "created_at": record["created_at"],
        "status": record["status"],
        "operation": record["operation"],
        "row_count": record["row_count"],
        "query_fingerprint": record["query_fingerprint"],
        "data_source": record["data_source"],
    }


class SyntheticApiService:
    """Mobile-facing service that is deliberately limited to synthetic fixtures."""

    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings
        self.registry = validate_metric_registry(settings.metrics_path)
        validate_passenger_flow_csv(settings.data_path)
        self.audit_store = AuditStore(settings.audit_dir)

    def _source_rows(self) -> list[dict[str, str]]:
        with self.settings.data_path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def catalog(self) -> dict[str, Any]:
        rows = self._source_rows()
        timestamps = sorted(
            datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) for row in rows
        )
        if len(set(timestamps)) > 1:
            unique = sorted(set(timestamps))
            interval = min(
                (later - earlier for earlier, later in zip(unique, unique[1:], strict=False)),
                default=timedelta(hours=1),
            )
        else:
            interval = timedelta(hours=1)
        default_end = timestamps[-1] + interval
        metrics = []
        for metric_id, definition in self.registry.items():
            metrics.append(
                {
                    "id": metric_id,
                    "label": _METRIC_LABELS.get(metric_id, metric_id),
                    "unit": definition.get("unit", "passengers"),
                    "dimensions": definition["dimensions"],
                }
            )
        return {
            "data_scope": "synthetic",
            "timezone": "Asia/Shanghai",
            "metrics": metrics,
            "dimensions": [
                {"id": value, "label": label} for value, label in _DIMENSION_LABELS.items()
            ],
            "lines": sorted({row["line_id"] for row in rows}),
            "stations": sorted({row["station_id"] for row in rows}),
            "directions": [
                {"id": "up", "label": "上行"},
                {"id": "down", "label": "下行"},
                {"id": "na", "label": "不区分"},
            ],
            "default_time_range": {
                "start": timestamps[0].isoformat(),
                "end": default_end.isoformat(),
            },
            "available_dates": sorted({value.date().isoformat() for value in timestamps}),
        }

    def query(self, request: QueryRequest) -> dict[str, Any]:
        query_ir = request.to_query_ir()
        result = execute_query(self.settings.metrics_path, self.settings.data_path, query_ir)
        fingerprint = _canonical_fingerprint(query_ir)
        audit = self.audit_store.write(
            "query",
            {
                "query_fingerprint": fingerprint,
                "query_ir": query_ir,
                "metric": result["metric"],
                "dimensions": result["dimensions"],
                "row_count": result["row_count"],
                "data_source": self.settings.data_path.name,
                "data_scope": "synthetic",
            },
        )
        return {**result, "audit": _audit_summary(audit)}

    def forecast(self, request: ForecastRequest) -> dict[str, Any]:
        source_rows = []
        for row in self._source_rows():
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.date() == request.reference_date:
                source_rows.append((timestamp, row))
        if not source_rows:
            raise ValueError(f"no synthetic rows for reference date {request.reference_date}")
        if len(source_rows) > request.limit:
            raise ValueError("forecast row limit reached; narrow the requested scope")

        rows: list[dict[str, Any]] = []
        for timestamp, row in source_rows:
            target_timestamp = datetime.combine(request.target_date, timestamp.timetz())
            rows.append(
                {
                    "timestamp": target_timestamp.isoformat(),
                    "line_id": row["line_id"],
                    "station_id": row["station_id"],
                    "direction": row["direction"],
                    "entries": int(row["entries"]),
                    "exits": int(row["exits"]),
                    "transfers": int(row["transfers"]),
                    "scheme_id": request.scheme_id,
                }
            )
        request_payload = request.model_dump(mode="json")
        fingerprint = _canonical_fingerprint(request_payload)
        audit = self.audit_store.write(
            "forecast",
            {
                "query_fingerprint": fingerprint,
                "reference_date": request.reference_date.isoformat(),
                "target_date": request.target_date.isoformat(),
                "scheme_id": request.scheme_id,
                "method": "reference_day_copy",
                "row_count": len(rows),
                "data_source": self.settings.data_path.name,
                "data_scope": "synthetic",
            },
        )
        return {
            "status": "answer",
            "method": "reference_day_copy",
            "reference_date": request.reference_date.isoformat(),
            "target_date": request.target_date.isoformat(),
            "scheme_id": request.scheme_id,
            "rows": rows,
            "row_count": len(rows),
            "audit": _audit_summary(audit),
        }

    def audit(self, audit_id: str) -> dict[str, Any]:
        return _audit_summary(self.audit_store.get(audit_id))
