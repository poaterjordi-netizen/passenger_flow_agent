from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from metro_agent import __version__
from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings

_FUNCTION_ROOT = Path(__file__).resolve().parent
_LOGGER = logging.getLogger(__name__)
_SERVICE: SyntheticApiService | None = None


class _RouteNotFound(Exception):
    pass


def _project_root() -> Path:
    configured = os.environ.get("METRO_AGENT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if (_FUNCTION_ROOT / "examples" / "synthetic_data").is_dir():
        return _FUNCTION_ROOT
    return _FUNCTION_ROOT.parents[3]


def _service() -> SyntheticApiService:
    global _SERVICE
    if _SERVICE is None:
        root = _project_root()
        data_dir = root / "examples" / "synthetic_data"
        _SERVICE = SyntheticApiService(
            ApiSettings(
                metrics_path=data_dir / "metrics.json",
                data_path=data_dir / "passenger_flow.csv",
                audit_dir=Path("/tmp/metro-agent-audits"),
                environment="cloudbase",
            )
        )
    return _SERVICE


def _response(status_code: int, data: Any) -> dict[str, Any]:
    return {"statusCode": status_code, "data": data}


def _route(event: dict[str, Any]) -> dict[str, Any]:
    path = event.get("path")
    method = str(event.get("method", "GET")).upper()
    payload = event.get("data")
    if payload is None:
        payload = {}
    if not isinstance(path, str) or not isinstance(payload, dict):
        raise ValueError("request path and data must be structured values")

    if method == "GET" and path == "/health":
        return {
            "status": "ok",
            "service": "metro-passenger-flow-api",
            "version": __version__,
            "environment": "cloudbase",
            "data_scope": "synthetic",
        }
    if method == "GET" and path == "/api/v1/catalog":
        return _service().catalog()
    if method == "POST" and path == "/api/v1/queries":
        return _service().query(QueryRequest.model_validate(payload))
    if method == "POST" and path == "/api/v1/forecasts/designated-day":
        return _service().forecast(ForecastRequest.model_validate(payload))
    if method == "GET" and path.startswith("/api/v1/audits/"):
        audit_id = path.removeprefix("/api/v1/audits/")
        try:
            return _service().audit(audit_id)
        except FileNotFoundError as exc:
            raise _RouteNotFound("audit not found") from exc
    raise _RouteNotFound("route not found")


def main(event: Any, context: Any) -> dict[str, Any]:
    del context
    if not isinstance(event, dict):
        return _response(
            422,
            {
                "error": {
                    "code": "invalid_request",
                    "message": "request must be an object",
                }
            },
        )
    try:
        return _response(200, _route(event))
    except ValidationError as exc:
        return _response(
            422,
            {
                "detail": exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            },
        )
    except _RouteNotFound as exc:
        return _response(404, {"detail": str(exc)})
    except ValueError as exc:
        return _response(422, {"error": {"code": "invalid_request", "message": str(exc)}})
    except Exception:
        _LOGGER.exception("unexpected CloudBase function failure")
        return _response(500, {"error": {"code": "internal_error", "message": "服务暂时不可用"}})
