from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> TimeRange:
        if self.start >= self.end:
            raise ValueError("time range start must be before end")
        return self


class ComparisonPeriods(StrictModel):
    baseline: TimeRange
    comparison: TimeRange
    relation: Literal["explicit", "previous_period", "year_over_year"] = "explicit"


class QueryFilter(StrictModel):
    field: Literal["line_id", "station_id", "direction"]
    operator: Literal["eq", "in"]
    value: str | list[str]


class QueryOrder(StrictModel):
    field: str = Field(min_length=1)
    direction: Literal["asc", "desc"] = "desc"


class QueryRequest(StrictModel):
    metric: str = Field(min_length=1)
    metric_version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    city: str | None = Field(default=None, min_length=1)
    dataset_role: Literal["actual", "reference", "forecast"] = "actual"
    source_version: str | None = Field(default=None, min_length=1)
    time_grain: Literal["source", "10m", "15m", "30m", "hour", "day"] = "source"
    time_basis: Literal["event_time", "service_day"] = "event_time"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    service_day: date | None = None
    calendar_version: str | None = Field(default=None, min_length=1)
    comparison_periods: ComparisonPeriods | None = None
    cross_midnight_policy: Literal["reject", "service_day_calendar"] = "reject"
    data_as_of: datetime | None = None
    time_range: TimeRange
    dimensions: list[Literal["line", "station", "direction", "time"]]
    filters: list[QueryFilter]
    order_by: list[QueryOrder] = Field(default_factory=list, max_length=2)
    limit: int = Field(default=100, ge=1, le=1000)

    def to_query_ir(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ForecastRequest(StrictModel):
    reference_date: date
    target_date: date
    scheme_id: int = Field(ge=0)
    limit: int = Field(default=1000, ge=1, le=1000)


class AuditSummary(StrictModel):
    audit_id: str
    created_at: str
    status: str
    operation: str
    row_count: int
    query_fingerprint: str
    data_source: str


class MetricCatalogItem(StrictModel):
    id: str
    label: str
    unit: str
    dimensions: list[str]
    version: str = "1.0.0"
    definition: str = ""
    logical_dataset: str = "synthetic_passenger_flow"
    dataset_role: Literal["actual", "reference", "forecast"] = "actual"
    allowed_grains: list[str] = Field(default_factory=lambda: ["source"])
    admission_status: Literal["approved", "candidate", "synthetic_only", "blocked"] = (
        "synthetic_only"
    )


class CatalogOption(StrictModel):
    id: str
    label: str


class CatalogResponse(StrictModel):
    data_scope: Literal["synthetic", "production-shadow", "production-readonly"]
    timezone: Literal["Asia/Shanghai"]
    metrics: list[MetricCatalogItem]
    dimensions: list[CatalogOption]
    lines: list[str]
    stations: list[str]
    directions: list[CatalogOption]
    default_time_range: TimeRange
    available_dates: list[date]
    city: str | None = None
    source_version: str | None = None
    quality_status: Literal["pass", "warning", "blocked", "unknown"] = "unknown"
    registration_status: Literal["approved", "candidate", "blocked", "unknown"] = "unknown"
    registration_quality_status: Literal["pass", "warning", "blocked", "unknown"] = "unknown"
    runtime_quality_status: Literal["pass", "warning", "blocked", "unknown"] = "unknown"
    freshness_status: Literal["fresh", "stale", "unknown", "not_applicable"] = "unknown"
    quality_gate_evaluated_at: str | None = None
    quality_gate: str | None = None
    access_policy: str | None = None
    logical_registry_version: str | None = None
    logical_registry_hash: str | None = None
    physical_mapping_version: str | None = None
    physical_mapping_hash: str | None = None


class QueryResponse(StrictModel):
    status: Literal["answer"]
    metric: str
    dimensions: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    audit: AuditSummary
    data_scope: Literal["synthetic", "production-shadow", "production-readonly"] = "synthetic"
    provenance: dict[str, Any] = Field(default_factory=dict)


class ForecastResponse(StrictModel):
    status: Literal["answer"]
    method: Literal["reference_day_copy"]
    reference_date: str
    target_date: str
    scheme_id: int
    rows: list[dict[str, Any]]
    row_count: int
    audit: AuditSummary


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    data_scope: Literal["synthetic", "production-shadow", "production-readonly"]
    data_status: Literal["synthetic-ready", "shadow-configured"] = "synthetic-ready"


class GovernanceIdentity(StrictModel):
    subject_id: str
    tenant_or_department: str
    roles: list[str]
    identity_adapter: Literal["static-token-single-subject"]
    multi_user_isolation: bool


class GovernanceAccessScope(StrictModel):
    allowed_cities: list[str]
    allowed_metrics: list[str]
    allowed_dataset_roles: list[Literal["actual", "reference", "forecast"]]
    max_time_range_hours: int
    row_limit: int
    export_policy: Literal["deny", "controlled"]
    policy_snapshot_id: str
    access_scope_hash: str


class GovernanceModelPolicy(StrictModel):
    endpoint_policy_id: str
    data_egress: Literal["deny", "synthetic-only", "aggregate-approved"]
    intent_egress: Literal["deny", "synthetic-only", "metadata-approved"]
    evidence_egress_allowed: bool
    intent_egress_allowed: bool
    active_provider: str
    active_model: str | None = None
    endpoint_target_hash: str
    endpoint_binding_verified: bool


class GovernanceDataSource(StrictModel):
    city: str | None = None
    source_version: str | None = None
    quality_status: Literal["pass", "warning", "blocked", "unknown"]
    registration_status: Literal["approved", "candidate", "blocked", "unknown"]
    registration_quality_status: Literal["pass", "warning", "blocked", "unknown"]
    runtime_quality_status: Literal["pass", "warning", "blocked", "unknown"]
    freshness_status: Literal["fresh", "stale", "unknown", "not_applicable"]
    quality_gate_evaluated_at: str | None = None
    quality_gate: str | None = None
    access_policy: str | None = None
    logical_registry_version: str | None = None
    logical_registry_hash: str | None = None
    physical_mapping_version: str | None = None
    physical_mapping_hash: str | None = None


class GovernancePromotionGate(StrictModel):
    gate_id: str
    configured_status: str
    enforced: bool
    ready: bool
    runtime_flag_requested: bool
    local_live_shadow_acknowledged: bool
    blockers: list[str]
    missing_owner_roles: list[str]
    missing_thresholds: list[str]
    pending_artifacts: list[str]


class GovernanceToolRegistry(StrictModel):
    registered_tools: list[str]
    tool_count: int


class GovernanceStatus(StrictModel):
    data_scope: Literal["synthetic", "production-shadow", "production-readonly"]
    assistant_enabled: bool
    assistant_status: Literal[
        "synthetic_baseline",
        "disabled_by_runtime_flag",
        "blocked_by_promotion_gate",
        "enabled_for_local_shadow",
        "enabled_after_promotion",
    ]
    identity: GovernanceIdentity
    access_scope: GovernanceAccessScope
    model_policy: GovernanceModelPolicy
    data_source: GovernanceDataSource
    promotion: GovernancePromotionGate
    tool_registry: GovernanceToolRegistry
