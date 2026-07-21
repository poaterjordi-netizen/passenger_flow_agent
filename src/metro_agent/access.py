from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from metro_agent.api.models import QueryRequest


class AccessContext(BaseModel):
    """Server-created authorization scope; never accepted from request bodies or prompts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    tenant_or_department: str = Field(min_length=1)
    roles: tuple[str, ...] = Field(min_length=1)
    allowed_cities: tuple[str, ...] = Field(min_length=1)
    allowed_metrics: tuple[str, ...] = Field(min_length=1)
    allowed_dataset_roles: tuple[Literal["actual", "reference", "forecast"], ...] = Field(
        min_length=1
    )
    max_time_range_hours: int = Field(ge=1, le=24 * 366)
    row_limit: int = Field(ge=1, le=1000)
    export_policy: Literal["deny", "controlled"] = "deny"
    policy_snapshot_id: str = Field(min_length=1)
    model_endpoint_policy_id: str = Field(min_length=1)
    model_data_egress: Literal["deny", "synthetic-only", "aggregate-approved"] = "deny"
    model_intent_egress: Literal["deny", "synthetic-only", "metadata-approved"] = "deny"
    model_allowed_provider: str | None = None
    model_allowed_model: str | None = None
    model_allowed_target_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def synthetic_local(cls) -> AccessContext:
        return cls(
            subject_id="local-synthetic-user",
            tenant_or_department="local-development",
            roles=("synthetic-reader",),
            allowed_cities=("synthetic",),
            allowed_metrics=("entries", "exits", "transfers", "net_inflow"),
            allowed_dataset_roles=("actual", "reference", "forecast"),
            max_time_range_hours=24 * 31,
            row_limit=1000,
            export_policy="controlled",
            policy_snapshot_id="local-synthetic-policy-v1",
            model_endpoint_policy_id="local-synthetic-model-policy-v1",
            model_data_egress="synthetic-only",
            model_intent_egress="synthetic-only",
        )

    def scope_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuthorizationService:
    """Deterministic authorization checks shared by API, tools, traces, and audits."""

    @staticmethod
    def authorize_query(context: AccessContext, request: QueryRequest) -> None:
        city = request.city or "synthetic"
        if city not in context.allowed_cities:
            raise PermissionError("query city is outside the authorized scope")
        if request.metric not in context.allowed_metrics:
            raise PermissionError("query metric is outside the authorized scope")
        if request.dataset_role not in context.allowed_dataset_roles:
            raise PermissionError("query dataset role is outside the authorized scope")
        if request.limit > context.row_limit:
            raise PermissionError("query row limit exceeds the authorized scope")
        if request.time_range.end - request.time_range.start > timedelta(
            hours=context.max_time_range_hours
        ):
            raise PermissionError("query time range exceeds the authorized scope")

    @staticmethod
    def authorize_owner(
        context: AccessContext,
        *,
        owner_subject_id: str,
        owner_tenant_or_department: str,
        access_scope_hash: str,
    ) -> None:
        if (
            owner_subject_id != context.subject_id
            or owner_tenant_or_department != context.tenant_or_department
            or access_scope_hash != context.scope_hash()
        ):
            raise PermissionError("object is outside the authorized owner scope")

    @staticmethod
    def authorize_export(context: AccessContext) -> None:
        if context.export_policy != "controlled":
            raise PermissionError("export is not authorized")

    @staticmethod
    def may_send_evidence_to_model(
        context: AccessContext,
        data_scope: str,
        endpoint_identity: dict[str, str] | None = None,
    ) -> bool:
        if context.model_data_egress == "aggregate-approved":
            return AuthorizationService.endpoint_matches(context, endpoint_identity)
        return context.model_data_egress == "synthetic-only" and data_scope == "synthetic"

    @staticmethod
    def may_send_intent_to_model(
        context: AccessContext,
        data_scope: str,
        endpoint_identity: dict[str, str] | None = None,
    ) -> bool:
        if context.model_intent_egress == "metadata-approved":
            return AuthorizationService.endpoint_matches(context, endpoint_identity)
        return context.model_intent_egress == "synthetic-only" and data_scope == "synthetic"

    @staticmethod
    def endpoint_matches(context: AccessContext, endpoint_identity: dict[str, str] | None) -> bool:
        if endpoint_identity is None:
            return False
        return (
            bool(context.model_allowed_provider)
            and context.model_allowed_provider == endpoint_identity.get("provider")
            and bool(context.model_allowed_model)
            and context.model_allowed_model == endpoint_identity.get("model")
            and bool(context.model_allowed_target_hash)
            and context.model_allowed_target_hash == endpoint_identity.get("target_hash")
        )
