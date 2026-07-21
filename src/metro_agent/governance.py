from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromotionOwners(_StrictModel):
    business_owner: str | None = None
    data_owner: str | None = None
    security_owner: str | None = None
    engineering_owner: str | None = None


class PromotionThresholds(_StrictModel):
    business_correctness_min: float | None = Field(default=None, ge=0, le=1)
    permission_leakage_max: float | None = Field(default=None, ge=0, le=1)
    city_or_version_drift_max: float | None = Field(default=None, ge=0, le=1)
    blocked_quality_execution_max: float | None = Field(default=None, ge=0, le=1)
    truncation_misstatement_max: float | None = Field(default=None, ge=0, le=1)
    unsupported_number_rate_max: float | None = Field(default=None, ge=0, le=1)
    deterministic_baseline_regression_max: float | None = Field(default=None, ge=0, le=1)
    query_timeout_seconds_max: float | None = Field(default=None, gt=0)
    query_cost_budget_max: float | None = Field(default=None, gt=0)
    database_timeout_retry_policy: Literal["no_automatic_retry"]


class PromotionArtifact(_StrictModel):
    status: Literal["pending", "approved", "rejected"] = "pending"
    approval_ref: str | None = Field(default=None, min_length=1)


class PromotionGateConfiguration(_StrictModel):
    schema_version: Literal["1.0"]
    gate_id: str = Field(min_length=1)
    status: Literal["blocked_pending_approval", "approved"]
    owners: PromotionOwners
    thresholds: PromotionThresholds
    required_artifacts: dict[str, PromotionArtifact] = Field(min_length=1)
    promotion_rule: str = Field(min_length=1)


@dataclass(frozen=True)
class PromotionGateEvaluation:
    gate_id: str
    configured_status: str
    ready: bool
    blockers: tuple[str, ...]
    missing_owner_roles: tuple[str, ...]
    missing_thresholds: tuple[str, ...]
    pending_artifacts: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> PromotionGateEvaluation:
        """Load the versioned gate and fail closed without leaking parser details."""

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            config = PromotionGateConfiguration.model_validate(raw)
        except (OSError, ValueError, TypeError):
            return cls(
                gate_id="unavailable",
                configured_status="invalid_configuration",
                ready=False,
                blockers=("promotion_gate_configuration_invalid",),
                missing_owner_roles=(),
                missing_thresholds=(),
                pending_artifacts=(),
            )

        missing_owners = tuple(
            sorted(name for name, value in config.owners.model_dump().items() if not value)
        )
        missing_thresholds = tuple(
            sorted(name for name, value in config.thresholds.model_dump().items() if value is None)
        )
        pending_artifacts = tuple(
            sorted(
                artifact_id
                for artifact_id, artifact in config.required_artifacts.items()
                if artifact.status != "approved" or not artifact.approval_ref
            )
        )
        blockers: list[str] = []
        if config.status != "approved":
            blockers.append("gate_status_not_approved")
        if missing_owners:
            blockers.append("owners_incomplete")
        if missing_thresholds:
            blockers.append("thresholds_incomplete")
        if pending_artifacts:
            blockers.append("required_artifacts_incomplete")
        return cls(
            gate_id=config.gate_id,
            configured_status=config.status,
            ready=not blockers,
            blockers=tuple(blockers),
            missing_owner_roles=missing_owners,
            missing_thresholds=missing_thresholds,
            pending_artifacts=pending_artifacts,
        )


AssistantAvailability = Literal[
    "synthetic_baseline",
    "disabled_by_runtime_flag",
    "blocked_by_promotion_gate",
    "enabled_for_local_shadow",
    "enabled_after_promotion",
]


def assistant_availability(
    *,
    data_scope: str,
    runtime_flag_requested: bool,
    promotion_gate: PromotionGateEvaluation,
    local_live_shadow_acknowledged: bool = False,
) -> tuple[bool, AssistantAvailability]:
    if data_scope == "synthetic":
        return True, "synthetic_baseline"
    if not runtime_flag_requested:
        return False, "disabled_by_runtime_flag"
    if promotion_gate.ready:
        return True, "enabled_after_promotion"
    if local_live_shadow_acknowledged:
        return True, "enabled_for_local_shadow"
    return False, "blocked_by_promotion_gate"
