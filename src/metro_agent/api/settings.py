from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from metro_agent.access import AccessContext


DataMode = Literal["synthetic", "production-shadow"]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolved_path(value: str | None, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(frozen=True)
class ApiSettings:
    """Runtime settings for the governed HTTP service.

    Paths and access tokens come from the process environment. No dotenv file is
    loaded, which keeps secrets outside the repository and matches the database
    adapter's runtime-only credential boundary.
    """

    metrics_path: Path
    data_path: Path
    audit_dir: Path
    environment: str = "development"
    access_token: str | None = None
    cors_origins: tuple[str, ...] = ()
    data_mode: DataMode = "synthetic"
    production_city: str | None = None
    production_source_version: str | None = None
    production_time_grain: str | None = None
    production_source_status: str = "blocked"
    production_default_start: str | None = None
    production_default_end: str | None = None
    production_registry_path: Path | None = None
    production_logical_registry_path: Path | None = None
    access_subject_id: str | None = None
    access_tenant_or_department: str | None = None
    access_roles: tuple[str, ...] = ()
    access_allowed_cities: tuple[str, ...] = ()
    access_allowed_metrics: tuple[str, ...] = ()
    access_allowed_dataset_roles: tuple[str, ...] = ()
    access_max_time_range_hours: int = 24
    access_row_limit: int = 100
    access_export_policy: str = "deny"
    access_policy_snapshot_id: str | None = None
    model_endpoint_policy_id: str | None = None
    model_data_egress: str = "deny"
    model_intent_egress: str = "deny"
    model_allowed_provider: str | None = None
    model_allowed_model: str | None = None
    model_allowed_target_hash: str | None = None
    production_assistant_enabled: bool = False
    local_live_shadow_acknowledged: bool = False
    promotion_gate_path: Path | None = None

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> ApiSettings:
        env = os.environ if environment is None else environment
        root = _resolved_path(env.get("METRO_AGENT_ROOT"), _repository_root())
        data_dir = _resolved_path(
            env.get("METRO_AGENT_DATA_DIR"), root / "examples" / "synthetic_data"
        )
        metrics_path = _resolved_path(env.get("METRO_API_METRICS_PATH"), data_dir / "metrics.json")
        data_path = _resolved_path(env.get("METRO_API_DATA_PATH"), data_dir / "passenger_flow.csv")
        audit_dir = _resolved_path(
            env.get("METRO_API_AUDIT_DIR"), root / "artifacts" / "api-audits"
        )
        origins = tuple(
            item.strip()
            for item in env.get("METRO_API_CORS_ORIGINS", "").split(",")
            if item.strip()
        )
        token = env.get("METRO_API_ACCESS_TOKEN", "").strip() or None
        data_mode = env.get("METRO_API_DATA_MODE", "synthetic").strip()
        if data_mode not in {"synthetic", "production-shadow"}:
            raise ValueError("METRO_API_DATA_MODE must be synthetic or production-shadow")
        return cls(
            metrics_path=metrics_path,
            data_path=data_path,
            audit_dir=audit_dir,
            environment=env.get("METRO_AGENT_ENV", "development").strip() or "development",
            access_token=token,
            cors_origins=origins,
            data_mode=data_mode,
            production_city=env.get("METRO_PRODUCTION_CITY", "").strip() or None,
            production_source_version=(
                env.get("METRO_PRODUCTION_SOURCE_VERSION", "").strip() or None
            ),
            production_time_grain=(env.get("METRO_PRODUCTION_TIME_GRAIN", "").strip() or None),
            production_source_status=(
                env.get("METRO_PRODUCTION_SOURCE_STATUS", "blocked").strip().lower() or "blocked"
            ),
            production_default_start=(
                env.get("METRO_PRODUCTION_DEFAULT_START", "").strip() or None
            ),
            production_default_end=(env.get("METRO_PRODUCTION_DEFAULT_END", "").strip() or None),
            production_registry_path=(
                _resolved_path(env.get("METRO_PRODUCTION_REGISTRY_PATH"), root)
                if env.get("METRO_PRODUCTION_REGISTRY_PATH", "").strip()
                else None
            ),
            production_logical_registry_path=_resolved_path(
                env.get("METRO_LOGICAL_REGISTRY_PATH"),
                root / "config" / "logical_data_products.json",
            ),
            access_subject_id=env.get("METRO_ACCESS_SUBJECT_ID", "").strip() or None,
            access_tenant_or_department=(
                env.get("METRO_ACCESS_TENANT_OR_DEPARTMENT", "").strip() or None
            ),
            access_roles=_csv_tuple(env.get("METRO_ACCESS_ROLES", "")),
            access_allowed_cities=_csv_tuple(env.get("METRO_ACCESS_ALLOWED_CITIES", "")),
            access_allowed_metrics=_csv_tuple(env.get("METRO_ACCESS_ALLOWED_METRICS", "")),
            access_allowed_dataset_roles=_csv_tuple(
                env.get("METRO_ACCESS_ALLOWED_DATASET_ROLES", "")
            ),
            access_max_time_range_hours=_positive_int(
                env.get("METRO_ACCESS_MAX_TIME_RANGE_HOURS", "24"),
                "METRO_ACCESS_MAX_TIME_RANGE_HOURS",
            ),
            access_row_limit=_positive_int(
                env.get("METRO_ACCESS_ROW_LIMIT", "100"), "METRO_ACCESS_ROW_LIMIT"
            ),
            access_export_policy=env.get("METRO_ACCESS_EXPORT_POLICY", "deny").strip(),
            access_policy_snapshot_id=(
                env.get("METRO_ACCESS_POLICY_SNAPSHOT_ID", "").strip() or None
            ),
            model_endpoint_policy_id=(
                env.get("METRO_MODEL_ENDPOINT_POLICY_ID", "").strip() or None
            ),
            model_data_egress=env.get("METRO_MODEL_DATA_EGRESS", "deny").strip(),
            model_intent_egress=env.get("METRO_MODEL_INTENT_EGRESS", "deny").strip(),
            model_allowed_provider=(env.get("METRO_MODEL_ALLOWED_PROVIDER", "").strip() or None),
            model_allowed_model=env.get("METRO_MODEL_ALLOWED_MODEL", "").strip() or None,
            model_allowed_target_hash=(
                env.get("METRO_MODEL_ALLOWED_TARGET_HASH", "").strip() or None
            ),
            production_assistant_enabled=(
                env.get("METRO_PRODUCTION_ASSISTANT_ENABLED", "false").strip().lower()
                in {"1", "true", "yes"}
            ),
            local_live_shadow_acknowledged=(
                env.get("METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED", "false").strip().lower()
                in {"1", "true", "yes"}
            ),
            promotion_gate_path=_resolved_path(
                env.get("METRO_PROMOTION_GATE_PATH"),
                root / "config" / "production_promotion_gates.json",
            ),
        )

    def resolved_promotion_gate_path(self) -> Path:
        return (
            self.promotion_gate_path
            or _repository_root() / "config" / "production_promotion_gates.json"
        ).resolve()

    def access_context(self) -> AccessContext:
        """Build the sole trusted request identity for the static-token adapter."""

        from metro_agent.access import AccessContext

        if self.data_mode == "synthetic" and not self.access_subject_id:
            return AccessContext.synthetic_local()
        required = {
            "METRO_ACCESS_SUBJECT_ID": self.access_subject_id,
            "METRO_ACCESS_TENANT_OR_DEPARTMENT": self.access_tenant_or_department,
            "METRO_ACCESS_ROLES": self.access_roles,
            "METRO_ACCESS_ALLOWED_CITIES": self.access_allowed_cities,
            "METRO_ACCESS_ALLOWED_METRICS": self.access_allowed_metrics,
            "METRO_ACCESS_ALLOWED_DATASET_ROLES": self.access_allowed_dataset_roles,
            "METRO_ACCESS_POLICY_SNAPSHOT_ID": self.access_policy_snapshot_id,
            "METRO_MODEL_ENDPOINT_POLICY_ID": self.model_endpoint_policy_id,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"access context is incomplete: {', '.join(missing)}")
        if self.access_export_policy not in {"deny", "controlled"}:
            raise ValueError("METRO_ACCESS_EXPORT_POLICY must be deny or controlled")
        if self.model_data_egress not in {"deny", "synthetic-only", "aggregate-approved"}:
            raise ValueError("METRO_MODEL_DATA_EGRESS is invalid")
        if self.model_intent_egress not in {"deny", "synthetic-only", "metadata-approved"}:
            raise ValueError("METRO_MODEL_INTENT_EGRESS is invalid")
        if (
            self.model_data_egress == "aggregate-approved"
            or self.model_intent_egress == "metadata-approved"
        ):
            endpoint_fields = {
                "METRO_MODEL_ALLOWED_PROVIDER": self.model_allowed_provider,
                "METRO_MODEL_ALLOWED_MODEL": self.model_allowed_model,
                "METRO_MODEL_ALLOWED_TARGET_HASH": self.model_allowed_target_hash,
            }
            missing_endpoint = sorted(name for name, value in endpoint_fields.items() if not value)
            if missing_endpoint:
                raise ValueError(
                    "approved model egress endpoint binding is incomplete: "
                    + ", ".join(missing_endpoint)
                )
        unsupported_roles = set(self.access_allowed_dataset_roles) - {
            "actual",
            "reference",
            "forecast",
        }
        if unsupported_roles:
            raise ValueError("access context contains unsupported dataset roles")
        return AccessContext(
            subject_id=str(self.access_subject_id),
            tenant_or_department=str(self.access_tenant_or_department),
            roles=self.access_roles,
            allowed_cities=self.access_allowed_cities,
            allowed_metrics=self.access_allowed_metrics,
            allowed_dataset_roles=self.access_allowed_dataset_roles,
            max_time_range_hours=self.access_max_time_range_hours,
            row_limit=self.access_row_limit,
            export_policy=self.access_export_policy,
            policy_snapshot_id=str(self.access_policy_snapshot_id),
            model_endpoint_policy_id=str(self.model_endpoint_policy_id),
            model_data_egress=self.model_data_egress,
            model_intent_egress=self.model_intent_egress,
            model_allowed_provider=self.model_allowed_provider,
            model_allowed_model=self.model_allowed_model,
            model_allowed_target_hash=self.model_allowed_target_hash,
        )


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed
