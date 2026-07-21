from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

from metro_agent.access import AccessContext, AuthorizationService
from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.settings import ApiSettings
from metro_agent.contracts import (
    validate_metric_registry,
    validate_passenger_flow_csv,
    validate_query_ir,
)
from metro_agent.database import query_template_hash
from metro_agent.query_engine import execute_query
from metro_agent.source_registry import load_logical_data_product, load_source_registration

if TYPE_CHECKING:
    from metro_agent.database import ReadOnlyMetroDatabase

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
_PRODUCTION_METRICS = {
    "entries": "InFlow",
    "exits": "OutFlow",
    "net_inflow": "net_inflow",
}


class SemanticCatalog(Protocol):
    data_scope: str

    def catalog(self, access_context: AccessContext | None = None) -> dict[str, Any]: ...


class QueryExecutor(Protocol):
    def query(
        self, request: QueryRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]: ...


class ForecastExecutor(Protocol):
    def forecast(
        self, request: ForecastRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]: ...


class AuditRepository(Protocol):
    def audit(
        self, audit_id: str, access_context: AccessContext | None = None
    ) -> dict[str, Any]: ...


class QualityService(Protocol):
    def quality_status(self, access_context: AccessContext | None = None) -> dict[str, Any]: ...


class EntityMetadataService(Protocol):
    def entity_labels(
        self,
        entity_type: str,
        request: QueryRequest,
        access_context: AccessContext | None = None,
    ) -> dict[str, str]: ...


class PassengerFlowDataService(
    SemanticCatalog,
    QueryExecutor,
    ForecastExecutor,
    AuditRepository,
    QualityService,
    EntityMetadataService,
    Protocol,
):
    """Thin façade shared by API/MCP; authorization and evidence stay separate services."""


@dataclass(frozen=True)
class ProductionSourcePolicy:
    city: str
    source_version: str
    time_grain: str
    status: str
    default_start: datetime
    default_end: datetime
    quality_gate: str
    access_policy: str
    logical_registry_version: str
    logical_registry_hash: str
    physical_mapping_version: str
    physical_mapping_hash: str
    semantic_status: str

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> ProductionSourcePolicy:
        required = {
            "METRO_PRODUCTION_CITY": settings.production_city,
            "METRO_PRODUCTION_SOURCE_VERSION": settings.production_source_version,
            "METRO_PRODUCTION_TIME_GRAIN": settings.production_time_grain,
            "METRO_PRODUCTION_DEFAULT_START": settings.production_default_start,
            "METRO_PRODUCTION_DEFAULT_END": settings.production_default_end,
            "METRO_PRODUCTION_REGISTRY_PATH": settings.production_registry_path,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"production-shadow metadata is incomplete: {', '.join(missing)}")
        if settings.production_source_status != "approved":
            raise ValueError("production-shadow source is not approved")
        if settings.production_time_grain not in {"10m", "15m", "30m", "hour", "day"}:
            raise ValueError("production time grain is unsupported")
        registry_path = Path(settings.production_registry_path).resolve()
        repository_root = Path(__file__).resolve().parents[3]
        if registry_path.is_relative_to(repository_root):
            raise ValueError("production source registry must remain outside the repository")
        registration = load_source_registration(
            registry_path,
            logical_dataset="fact_station_flow_actual",
            city=str(settings.production_city),
            source_version=str(settings.production_source_version),
        )
        logical_registry_path = (
            settings.production_logical_registry_path
            or repository_root / "config" / "logical_data_products.json"
        )
        logical_product = load_logical_data_product(
            Path(logical_registry_path).resolve(), "fact_station_flow_actual"
        )
        if set(logical_product.metric_ids) != set(_PRODUCTION_METRICS):
            raise ValueError("logical registry metrics disagree with the production adapter")
        if registration.quality_gate != logical_product.quality_gate_id:
            raise ValueError("physical source quality gate disagrees with the logical registry")
        if registration.access_policy != logical_product.access_policy_id:
            raise ValueError("physical source access policy disagrees with the logical registry")
        if registration.time_grain != settings.production_time_grain:
            raise ValueError("production metadata disagrees with the source registry")
        try:
            configured_start = datetime.fromisoformat(
                str(settings.production_default_start).replace("Z", "+00:00")
            )
            configured_end = datetime.fromisoformat(
                str(settings.production_default_end).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("production default range is invalid") from exc
        if (
            configured_start.tzinfo is None
            or configured_end.tzinfo is None
            or configured_start >= configured_end
        ):
            raise ValueError("production default range must be timezone-aware and ordered")
        if (
            configured_start != registration.default_start
            or configured_end != registration.default_end
        ):
            raise ValueError("production default range disagrees with the source registry")
        return cls(
            city=str(settings.production_city),
            source_version=str(settings.production_source_version),
            time_grain=str(settings.production_time_grain),
            status=settings.production_source_status,
            default_start=registration.default_start,
            default_end=registration.default_end,
            quality_gate=registration.quality_gate,
            access_policy=registration.access_policy,
            logical_registry_version=logical_product.registry_version,
            logical_registry_hash=logical_product.registry_hash,
            physical_mapping_version=registration.physical_mapping_version,
            physical_mapping_hash=registration.physical_mapping_hash,
            semantic_status=registration.semantic_status,
        )


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuditStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        operation: str,
        payload: dict[str, Any],
        access_context: AccessContext | None = None,
    ) -> dict[str, Any]:
        context = access_context or AccessContext.synthetic_local()
        if operation not in {"query", "forecast"}:
            raise ValueError("unsupported audit operation")
        audit_id = f"{operation}-{uuid.uuid4().hex}"
        record = {
            "schema_version": "1.0",
            "audit_id": audit_id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "succeeded",
            "operation": operation,
            "owner_subject_id": context.subject_id,
            "owner_tenant_or_department": context.tenant_or_department,
            "access_scope_hash": context.scope_hash(),
            "policy_snapshot_id": context.policy_snapshot_id,
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

    def get(self, audit_id: str, access_context: AccessContext | None = None) -> dict[str, Any]:
        if not _AUDIT_ID.fullmatch(audit_id):
            raise ValueError("invalid audit id")
        path = self.directory / f"{audit_id}.json"
        if not path.is_file():
            raise FileNotFoundError(audit_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("audit_id") != audit_id:
            raise ValueError("invalid audit record")
        context = access_context or AccessContext.synthetic_local()
        AuthorizationService.authorize_owner(
            context,
            owner_subject_id=str(payload.get("owner_subject_id", "")),
            owner_tenant_or_department=str(payload.get("owner_tenant_or_department", "")),
            access_scope_hash=str(payload.get("access_scope_hash", "")),
        )
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

    data_scope = "synthetic"

    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings
        self.registry = validate_metric_registry(settings.metrics_path)
        validate_passenger_flow_csv(settings.data_path)
        self.audit_store = AuditStore(settings.audit_dir)

    def _source_rows(self) -> list[dict[str, str]]:
        with self.settings.data_path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def catalog(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = access_context or AccessContext.synthetic_local()
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
                    "label": definition.get("label", _METRIC_LABELS.get(metric_id, metric_id)),
                    "unit": definition.get("unit", "passengers"),
                    "dimensions": definition["dimensions"],
                    "version": definition.get("version", "1.0.0"),
                    "definition": definition.get("definition", ""),
                    "logical_dataset": definition.get(
                        "logical_dataset", "synthetic_passenger_flow"
                    ),
                    "dataset_role": definition.get("dataset_role", "actual"),
                    "allowed_grains": ["source"],
                    "admission_status": definition.get("admission_status", "synthetic_only"),
                }
            )
        return {
            "data_scope": "synthetic",
            "timezone": "Asia/Shanghai",
            "metrics": [item for item in metrics if item["id"] in context.allowed_metrics],
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
            "city": "synthetic",
            "source_version": "synthetic-v1",
            "quality_status": "pass",
            "registration_status": "approved",
            "registration_quality_status": "pass",
            "runtime_quality_status": "pass",
            "freshness_status": "not_applicable",
        }

    def query(
        self, request: QueryRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]:
        context = access_context or AccessContext.synthetic_local()
        query_ir = request.to_query_ir()
        validate_query_ir(query_ir, self.registry, "synthetic query")
        AuthorizationService.authorize_query(context, request)
        bounded_full_ir = {**query_ir, "limit": 1000}
        full_result = execute_query(
            self.settings.metrics_path, self.settings.data_path, bounded_full_ir
        )
        matched_row_count = full_result["row_count"]
        rows = full_result["rows"][: request.limit]
        result = {**full_result, "rows": rows, "row_count": len(rows)}
        truncated = matched_row_count > len(rows)
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
            context,
        )
        definition = self.registry[request.metric]
        return {
            **result,
            "audit": _audit_summary(audit),
            "data_scope": self.data_scope,
            "provenance": {
                "metric_id": request.metric,
                "metric_version": definition.get("version", "1.0.0"),
                "metric_unit": definition.get("unit", "passengers"),
                "aggregation": definition.get("aggregation"),
                "missing_value_policy": definition.get("missing_value_policy", "reject"),
                "city": request.city or "synthetic",
                "dataset_role": request.dataset_role,
                "source_version": request.source_version or "synthetic-v1",
                "time_grain": request.time_grain,
                "quality_status": "pass",
                "registration_status": "approved",
                "registration_quality_status": "pass",
                "runtime_quality_status": "pass",
                "quality_flags": [],
                "freshness_status": "not_applicable",
                "truncated": truncated,
                "complete": not truncated,
                "returned_row_count": result["row_count"],
                "matched_row_count": matched_row_count,
                "query_fingerprint": fingerprint,
                "policy_snapshot_id": context.policy_snapshot_id,
                "access_scope_hash": context.scope_hash(),
                "audit_id": audit["audit_id"],
            },
        }

    def entity_labels(
        self,
        entity_type: str,
        request: QueryRequest,
        access_context: AccessContext | None = None,
    ) -> dict[str, str]:
        if entity_type not in {"station", "line"}:
            raise ValueError("entity_type must be station or line")
        catalog = self.catalog(access_context)
        values = catalog["stations" if entity_type == "station" else "lines"]
        return {str(value): str(value) for value in values}

    def forecast(
        self, request: ForecastRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]:
        context = access_context or AccessContext.synthetic_local()
        if "forecast" not in context.allowed_dataset_roles:
            raise PermissionError("forecast dataset role is outside the authorized scope")
        if request.limit > context.row_limit:
            raise PermissionError("forecast row limit exceeds the authorized scope")
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
            output_row: dict[str, Any] = {
                "timestamp": target_timestamp.isoformat(),
                "line_id": row["line_id"],
                "station_id": row["station_id"],
                "direction": row["direction"],
                "scheme_id": request.scheme_id,
            }
            for metric in ("entries", "exits", "transfers"):
                if metric in context.allowed_metrics:
                    output_row[metric] = int(row[metric])
            if "net_inflow" in context.allowed_metrics:
                output_row["net_inflow"] = int(row["entries"]) - int(row["exits"])
            rows.append(output_row)
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
                "authorized_metrics": list(context.allowed_metrics),
            },
            context,
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

    def audit(self, audit_id: str, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = access_context or AccessContext.synthetic_local()
        return _audit_summary(self.audit_store.get(audit_id, context))

    def quality_status(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        del access_context
        return {
            "status": "pass",
            "data_scope": self.data_scope,
            "registration_status": "approved",
            "registration_quality_status": "pass",
            "runtime_quality_status": "pass",
            "freshness_status": "not_applicable",
            "flags": [],
            "source_version": "synthetic-v1",
        }


class MetroflowReadOnlyDataService:
    """Fail-closed production-shadow service over the repository's fixed MySQL routes."""

    data_scope = "production-shadow"

    def __init__(
        self,
        settings: ApiSettings,
        database: ReadOnlyMetroDatabase,
        policy: ProductionSourcePolicy,
    ) -> None:
        self.settings = settings
        self.database = database
        self.policy = policy
        self.registry = validate_metric_registry(settings.metrics_path)
        self.audit_store = AuditStore(settings.audit_dir)
        self._source_cache_lock = threading.Lock()
        self._source_cache: tuple[tuple[Any, ...], float, Any] | None = None

    def catalog(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = _require_production_access(access_context)
        metrics = []
        for metric_id in _PRODUCTION_METRICS:
            definition = self.registry[metric_id]
            metrics.append(
                {
                    "id": metric_id,
                    "label": definition.get("label", _METRIC_LABELS.get(metric_id, metric_id)),
                    "unit": definition.get("unit", "passengers"),
                    "dimensions": [
                        value
                        for value in definition["dimensions"]
                        if value in {"line", "station", "time"}
                    ],
                    "version": definition.get("version", "1.0.0"),
                    "definition": definition.get("definition", ""),
                    "logical_dataset": definition.get(
                        "logical_dataset", "fact_station_flow_actual"
                    ),
                    "dataset_role": "actual",
                    "allowed_grains": ["source", self.policy.time_grain],
                    "admission_status": "candidate",
                }
            )
        return {
            "data_scope": self.data_scope,
            "timezone": "Asia/Shanghai",
            "metrics": [item for item in metrics if item["id"] in context.allowed_metrics],
            "dimensions": [
                {"id": value, "label": _DIMENSION_LABELS[value]}
                for value in ("line", "station", "time")
            ],
            "lines": [],
            "stations": [],
            "directions": [],
            "default_time_range": {
                "start": self.policy.default_start.isoformat(),
                "end": self.policy.default_end.isoformat(),
            },
            "available_dates": [self.policy.default_start.date().isoformat()],
            "city": self.policy.city,
            "quality_gate": self.policy.quality_gate,
            "access_policy": self.policy.access_policy,
            "source_version": self.policy.source_version,
            "logical_registry_version": self.policy.logical_registry_version,
            "logical_registry_hash": self.policy.logical_registry_hash,
            "physical_mapping_version": self.policy.physical_mapping_version,
            "physical_mapping_hash": self.policy.physical_mapping_hash,
            "quality_status": "unknown",
            "registration_status": "approved",
            "registration_quality_status": self._registration_quality_status,
            "runtime_quality_status": "unknown",
            "freshness_status": "unknown",
            "quality_gate_evaluated_at": None,
        }

    def quality_status(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        _require_production_access(access_context)
        return {
            "status": "unknown",
            "data_scope": self.data_scope,
            "registration_status": "approved",
            "registration_quality_status": self._registration_quality_status,
            "runtime_quality_status": "unknown",
            "freshness_status": "unknown",
            "quality_gate_evaluated_at": None,
            "flags": self._quality_flags(
                "source registration passed, but runtime quality is unknown before a query"
            ),
            "source_version": self.policy.source_version,
            "city": self.policy.city,
        }

    def query(
        self, request: QueryRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]:
        context = _require_production_access(access_context)
        AuthorizationService.authorize_query(context, request)
        validate_query_ir(request.to_query_ir(), self.registry, "production query")
        self._validate_request(request)
        start, end = self._local_naive_range(request)
        station_ids = _filter_values(request, "station_id")
        line_ids = _filter_values(request, "line_id")
        result, source_query_cache_hit = self._query_source(
            start,
            end,
            station_ids=station_ids,
            line_ids=line_ids,
        )
        if result.truncated:
            raise ValueError("production query was truncated; narrow the requested scope")
        rows, total_group_count, quality = self._aggregate_rows(request, result.rows)
        if self.policy.semantic_status != "verified":
            quality["quality_decision"] = "warning"
        output_truncated = total_group_count > len(rows)
        fingerprint = _canonical_fingerprint(request.to_query_ir())
        audit = self.audit_store.write(
            "query",
            {
                "query_fingerprint": fingerprint,
                "metric": request.metric,
                "dimensions": request.dimensions,
                "row_count": len(rows),
                "data_source": "fact_station_flow_actual",
                "data_scope": self.data_scope,
                "resolved_source_version": self.policy.source_version,
                "logical_registry_version": self.policy.logical_registry_version,
                "logical_registry_hash": self.policy.logical_registry_hash,
                "physical_mapping_version": self.policy.physical_mapping_version,
                "physical_mapping_hash": self.policy.physical_mapping_hash,
                "query_template_id": result.dataset,
                "query_template_hash": query_template_hash(result.sql_template),
                "parameter_count": result.parameter_count,
                "tls_active": bool(result.tls_cipher),
                "tls_identity_mode": result.tls_identity_mode,
                "source_query_cache_hit": source_query_cache_hit,
                "transaction_mode": "read_only_rollback",
                "runtime_quality": quality,
            },
            context,
        )
        event_times = [row.get("StartTime") for row in result.rows if row.get("StartTime")]
        latest = max(event_times).isoformat() if event_times else None
        return {
            "status": "answer",
            "metric": request.metric,
            "dimensions": request.dimensions,
            "rows": rows,
            "row_count": len(rows),
            "audit": _audit_summary(audit),
            "data_scope": self.data_scope,
            "provenance": {
                "metric_id": request.metric,
                "metric_version": request.metric_version,
                "metric_unit": self.registry[request.metric].get("unit", "passengers"),
                "aggregation": self.registry[request.metric].get("aggregation"),
                "missing_value_policy": self.registry[request.metric].get(
                    "missing_value_policy", "reject"
                ),
                "city": self.policy.city,
                "dataset_role": "actual",
                "source_version": self.policy.source_version,
                "resolved_source_version": self.policy.source_version,
                "logical_registry_version": self.policy.logical_registry_version,
                "logical_registry_hash": self.policy.logical_registry_hash,
                "physical_mapping_version": self.policy.physical_mapping_version,
                "physical_mapping_hash": self.policy.physical_mapping_hash,
                "time_grain": request.time_grain,
                "registration_status": "approved",
                "registration_quality_status": self._registration_quality_status,
                "runtime_quality_status": quality["quality_decision"],
                "quality_status": quality["quality_decision"],
                "quality_gate": self.policy.quality_gate,
                "quality_gate_evaluated_at": quality["evaluated_at"],
                "access_policy": self.policy.access_policy,
                "quality_flags": self._quality_flags(),
                "freshness_status": "unknown",
                "source_event_time_max": latest,
                "source_row_count": quality["source_row_count"],
                "missing_row_count": quality["missing_row_count"],
                "invalid_row_count": quality["invalid_row_count"],
                "query_template_id": result.dataset,
                "query_template_hash": query_template_hash(result.sql_template),
                "parameter_count": result.parameter_count,
                "tls_active": bool(result.tls_cipher),
                "tls_identity_verified": True,
                "tls_identity_mode": result.tls_identity_mode,
                "source_query_cache_hit": source_query_cache_hit,
                "transaction_mode": "read_only_rollback",
                "truncated": output_truncated,
                "complete": not output_truncated,
                "returned_row_count": len(rows),
                "matched_row_count": total_group_count,
                "query_fingerprint": fingerprint,
                "policy_snapshot_id": context.policy_snapshot_id,
                "access_scope_hash": context.scope_hash(),
                "total_group_count": total_group_count,
                "audit_id": audit["audit_id"],
            },
        }

    def entity_labels(
        self,
        entity_type: str,
        request: QueryRequest,
        access_context: AccessContext | None = None,
    ) -> dict[str, str]:
        if entity_type not in {"station", "line"}:
            raise ValueError("entity_type must be station or line")
        context = _require_production_access(access_context)
        AuthorizationService.authorize_query(context, request)
        validate_query_ir(request.to_query_ir(), self.registry, "production entity metadata")
        self._validate_request(request)
        start, end = self._local_naive_range(request)
        result, _ = self._query_source(
            start,
            end,
            station_ids=_filter_values(request, "station_id"),
            line_ids=_filter_values(request, "line_id"),
        )
        if result.truncated:
            raise ValueError("production entity metadata query was truncated")

        id_field = "StationID" if entity_type == "station" else "LineID"
        name_field = "StationName" if entity_type == "station" else "LineName"
        labels: dict[str, str] = {}
        for row in result.rows:
            entity_id = row.get(id_field) or (row.get(name_field) if entity_type == "line" else None)
            if entity_id is None or not str(entity_id).strip():
                raise ValueError("production entity metadata contains a missing identifier")
            normalized_id = str(entity_id).strip()
            normalized_name = str(row.get(name_field) or normalized_id).strip()
            previous = labels.get(normalized_id)
            if previous is not None and previous != normalized_name:
                raise ValueError("production entity metadata contains conflicting names")
            labels[normalized_id] = normalized_name
        return labels

    @property
    def _registration_quality_status(self) -> str:
        return "pass" if self.policy.semantic_status == "verified" else "warning"

    def _quality_flags(self, *extra: str) -> list[str]:
        flags = [*extra, "production-shadow results are not admitted for operational decisions"]
        if self.policy.semantic_status != "verified":
            flags.append(
                "source city and business semantics are unverified; use for local shadow only"
            )
        return flags

    def _query_source(
        self,
        start: datetime,
        end: datetime,
        *,
        station_ids: list[str] | None,
        line_ids: list[str] | None,
    ) -> tuple[Any, bool]:
        key = (
            start,
            end,
            tuple(station_ids or ()),
            tuple(line_ids or ()),
        )
        with self._source_cache_lock:
            now = time.monotonic()
            if self._source_cache is not None:
                cached_key, cached_at, cached_result = self._source_cache
                if cached_key == key and now - cached_at <= 10:
                    return cached_result, True
            result = self.database.query_station_flow_day(
                start.date(),
                station_ids=station_ids,
                line_ids=line_ids,
                start_time=start,
                end_time=end,
                limit=50_000,
            )
            self._source_cache = (key, time.monotonic(), result)
            return result, False

    def _validate_request(self, request: QueryRequest) -> None:
        if request.metric not in _PRODUCTION_METRICS:
            raise ValueError("metric is not admitted for production-shadow")
        if request.city != self.policy.city:
            raise ValueError("production query city is missing or not authorized")
        if request.dataset_role != "actual":
            raise ValueError("production-shadow station flow supports actual data only")
        if request.source_version != self.policy.source_version:
            raise ValueError("production query source_version is missing or not authorized")
        if request.time_grain not in {"source", self.policy.time_grain}:
            raise ValueError("production query time_grain does not match the approved source")
        if request.time_basis != "event_time" or request.timezone != "Asia/Shanghai":
            raise ValueError("approved station-flow source supports Asia/Shanghai event_time only")
        if request.service_day is not None or request.calendar_version is not None:
            raise ValueError("production-shadow does not support service-day fields")
        if request.data_as_of is not None:
            raise ValueError("production-shadow does not support data_as_of")
        if request.cross_midnight_policy != "reject":
            raise ValueError("cross-midnight service-day queries are not yet admitted")
        if (
            request.time_range.start < self.policy.default_start
            or request.time_range.end > self.policy.default_end
        ):
            raise ValueError("production query time range is outside the approved source range")
        if "direction" in request.dimensions or any(
            item.field == "direction" for item in request.filters
        ):
            raise ValueError("direction is not admitted for the approved station-flow source")

    @staticmethod
    def _local_naive_range(request: QueryRequest) -> tuple[datetime, datetime]:
        start = request.time_range.start
        end = request.time_range.end
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("production query time range must include timezone")
        timezone = ZoneInfo("Asia/Shanghai")
        local_start = start.astimezone(timezone).replace(tzinfo=None)
        local_end = end.astimezone(timezone).replace(tzinfo=None)
        if local_start >= local_end:
            raise ValueError("production query start must be before end")
        if local_start.date() != (local_end - timedelta(microseconds=1)).date():
            raise ValueError("production-shadow station query must fit one service day")
        return local_start, local_end

    @staticmethod
    def _aggregate_rows(
        request: QueryRequest, source_rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        totals: dict[tuple[Any, ...], float] = {}
        key_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        for source in source_rows:
            dimension_row: dict[str, Any] = {}
            for dimension in request.dimensions:
                if dimension == "line":
                    dimension_row[dimension] = source.get("LineID") or source.get("LineName")
                elif dimension == "station":
                    dimension_row[dimension] = source.get("StationID")
                elif dimension == "time":
                    value = source.get("StartTime")
                    dimension_row[dimension] = (
                        value.isoformat() if hasattr(value, "isoformat") else value
                    )
            key = tuple(dimension_row.get(value) for value in request.dimensions)
            if request.metric == "entries":
                metric_value = _required_flow_value(source, "InFlow")
            elif request.metric == "exits":
                metric_value = _required_flow_value(source, "OutFlow")
            else:
                metric_value = _required_flow_value(source, "InFlow") - _required_flow_value(
                    source, "OutFlow"
                )
            totals[key] = totals.get(key, 0) + metric_value
            key_rows[key] = dimension_row
        rows = [
            {**key_rows[key], request.metric: _normalized_number(value)}
            for key, value in totals.items()
        ]
        if request.order_by:
            for order in reversed(request.order_by):
                rows.sort(
                    key=lambda row: (row.get(order.field) is None, row.get(order.field)),
                    reverse=order.direction == "desc",
                )
        else:
            rows.sort(
                key=lambda row: tuple(str(row.get(value, "")) for value in request.dimensions)
            )
        return (
            rows[: request.limit],
            len(rows),
            {
                "source_row_count": len(source_rows),
                "missing_row_count": 0,
                "invalid_row_count": 0,
                "quality_decision": "pass",
                "evaluated_at": datetime.now(UTC).isoformat(),
            },
        )

    def forecast(
        self, request: ForecastRequest, access_context: AccessContext | None = None
    ) -> dict[str, Any]:
        del request, access_context
        raise ValueError("forecast is not admitted for production-shadow")

    def audit(self, audit_id: str, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = _require_production_access(access_context)
        return _audit_summary(self.audit_store.get(audit_id, context))


def create_data_service(
    settings: ApiSettings,
    *,
    environment: Mapping[str, str] | None = None,
    database: ReadOnlyMetroDatabase | None = None,
) -> PassengerFlowDataService:
    if settings.data_mode == "synthetic":
        return SyntheticApiService(settings)
    if not settings.access_token:
        raise ValueError("production-shadow requires an API access token")
    access_context = settings.access_context()
    from metro_agent.database import DatabaseSettings, ReadOnlyMetroDatabase

    policy = ProductionSourcePolicy.from_settings(settings)
    if policy.city not in access_context.allowed_cities:
        raise ValueError("production source city is outside the configured access context")
    if not set(_PRODUCTION_METRICS).intersection(access_context.allowed_metrics):
        raise ValueError("production access context admits no production metric")
    if "actual" not in access_context.allowed_dataset_roles:
        raise ValueError("production access context must admit the actual dataset role")
    if database is None:
        database_settings = DatabaseSettings.from_env(environment)
        if database_settings.allow_insecure_tls or not database_settings.ssl_ca:
            raise ValueError("production-shadow requires verified TLS")
        database_settings.connection_kwargs()
        database = ReadOnlyMetroDatabase(database_settings)
    return MetroflowReadOnlyDataService(settings, database, policy)


def _require_production_access(access_context: AccessContext | None) -> AccessContext:
    if access_context is None:
        raise PermissionError("production access context is required")
    return access_context


def _filter_values(request: QueryRequest, field: str) -> list[str] | None:
    values: list[str] = []
    for item in request.filters:
        if item.field != field:
            continue
        if item.operator == "eq":
            values.append(str(item.value))
        else:
            values.extend(str(value) for value in item.value)
    return values or None


def _required_flow_value(source: dict[str, Any], field: str) -> float:
    if field not in source or source[field] is None:
        raise ValueError(f"production source has a missing required value for {field}")
    value = source[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"production source has an invalid numeric value for {field}")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"production source has an invalid non-negative value for {field}")
    return normalized


def _normalized_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value
