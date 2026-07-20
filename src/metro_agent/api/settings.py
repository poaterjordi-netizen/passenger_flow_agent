from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolved_path(value: str | None, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(frozen=True)
class ApiSettings:
    """Runtime settings for the synthetic-only HTTP service.

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

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> ApiSettings:
        env = os.environ if environment is None else environment
        root = _resolved_path(env.get("METRO_AGENT_ROOT"), _repository_root())
        data_dir = _resolved_path(
            env.get("METRO_AGENT_DATA_DIR"), root / "examples" / "synthetic_data"
        )
        metrics_path = _resolved_path(
            env.get("METRO_API_METRICS_PATH"), data_dir / "metrics.json"
        )
        data_path = _resolved_path(
            env.get("METRO_API_DATA_PATH"), data_dir / "passenger_flow.csv"
        )
        audit_dir = _resolved_path(
            env.get("METRO_API_AUDIT_DIR"), root / "artifacts" / "api-audits"
        )
        origins = tuple(
            item.strip()
            for item in env.get("METRO_API_CORS_ORIGINS", "").split(",")
            if item.strip()
        )
        token = env.get("METRO_API_ACCESS_TOKEN", "").strip() or None
        return cls(
            metrics_path=metrics_path,
            data_path=data_path,
            audit_dir=audit_dir,
            environment=env.get("METRO_AGENT_ENV", "development").strip() or "development",
            access_token=token,
            cors_origins=origins,
        )
