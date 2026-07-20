from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(StrictModel):
    start: datetime
    end: datetime


class QueryFilter(StrictModel):
    field: Literal["line_id", "station_id", "direction"]
    operator: Literal["eq", "in"]
    value: str | list[str]


class QueryRequest(StrictModel):
    metric: str = Field(min_length=1)
    time_range: TimeRange
    dimensions: list[Literal["line", "station", "direction", "time"]]
    filters: list[QueryFilter]
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


class CatalogOption(StrictModel):
    id: str
    label: str


class CatalogResponse(StrictModel):
    data_scope: Literal["synthetic"]
    timezone: Literal["Asia/Shanghai"]
    metrics: list[MetricCatalogItem]
    dimensions: list[CatalogOption]
    lines: list[str]
    stations: list[str]
    directions: list[CatalogOption]
    default_time_range: TimeRange
    available_dates: list[date]


class QueryResponse(StrictModel):
    status: Literal["answer"]
    metric: str
    dimensions: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    audit: AuditSummary


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
    data_scope: Literal["synthetic"]
