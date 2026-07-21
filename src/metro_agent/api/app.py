from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metro_agent import __version__
from metro_agent.access import AccessContext, AuthorizationService
from metro_agent.api.models import (
    AuditSummary,
    CatalogResponse,
    ForecastRequest,
    ForecastResponse,
    GovernanceStatus,
    HealthResponse,
    QueryRequest,
    QueryResponse,
)
from metro_agent.api.service import PassengerFlowDataService, create_data_service
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.provider import provider_endpoint_identity
from metro_agent.assistant.schemas import (
    AssistantCapabilities,
    AssistantMessageRequest,
    HumanFeedbackRequest,
    RunRecord,
    SessionRecord,
)
from metro_agent.governance import PromotionGateEvaluation, assistant_availability

_bearer = HTTPBearer(auto_error=False)


def _service(request: Request) -> PassengerFlowDataService:
    return request.app.state.service


def _assistant(request: Request) -> AssistantService:
    return request.app.state.assistant


def _authorize(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AccessContext:
    configured = request.app.state.settings.access_token
    if configured is None:
        return getattr(
            request.app.state, "access_context", request.app.state.settings.access_context()
        )
    supplied = credentials.credentials if credentials and credentials.scheme == "Bearer" else ""
    if not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return getattr(request.app.state, "access_context", request.app.state.settings.access_context())


def _resolved_access(value: object, fallback: AccessContext) -> AccessContext:
    return value if isinstance(value, AccessContext) else fallback


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    runtime = settings or ApiSettings.from_env()
    application = FastAPI(
        title="Metro Passenger Flow API",
        summary="Governed passenger-flow query API with a synthetic baseline",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.settings = runtime
    application.state.access_context = runtime.access_context()
    application.state.service = create_data_service(runtime)
    application.state.promotion_gate = PromotionGateEvaluation.load(
        runtime.resolved_promotion_gate_path()
    )
    assistant_enabled, assistant_status = assistant_availability(
        data_scope=application.state.service.data_scope,
        runtime_flag_requested=runtime.production_assistant_enabled,
        promotion_gate=application.state.promotion_gate,
        local_live_shadow_acknowledged=runtime.local_live_shadow_acknowledged,
    )
    application.state.assistant_enabled = assistant_enabled
    application.state.assistant_status = assistant_status
    application.state.assistant = AssistantService(
        application.state.service,
        runtime.audit_dir.parent / "assistant",
        default_access_context=application.state.access_context,
        production_enabled=assistant_enabled,
    )

    if runtime.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(runtime.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @application.exception_handler(ValueError)
    async def invalid_request_handler(_: Request, __: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "request failed validation",
                }
            },
        )

    @application.exception_handler(RuntimeError)
    async def provider_failure_handler(_: Request, __: RuntimeError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": {
                    "code": "provider_failure",
                    "message": "assistant provider failed safely",
                }
            },
        )

    @application.exception_handler(PermissionError)
    async def authorization_failure_handler(_: Request, __: PermissionError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "forbidden",
                    "message": "request is outside the authorized scope",
                }
            },
        )

    @application.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "metro-passenger-flow-api", "docs": "/docs"}

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "metro-passenger-flow-api",
            "version": __version__,
            "environment": runtime.environment,
            "data_scope": application.state.service.data_scope,
            "data_status": (
                "synthetic-ready"
                if application.state.service.data_scope == "synthetic"
                else "shadow-configured"
            ),
        }

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(_authorize)])

    @router.get(
        "/governance/status",
        response_model=GovernanceStatus,
        tags=["governance"],
    )
    def governance_status(
        service: PassengerFlowDataService = Depends(_service),
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        context = _resolved_access(access_context, application.state.access_context)
        catalog_snapshot = service.catalog(context)
        gate = application.state.promotion_gate
        endpoint_identity = provider_endpoint_identity(assistant.provider)
        return {
            "data_scope": service.data_scope,
            "assistant_enabled": application.state.assistant_enabled,
            "assistant_status": application.state.assistant_status,
            "identity": {
                "subject_id": context.subject_id,
                "tenant_or_department": context.tenant_or_department,
                "roles": list(context.roles),
                "identity_adapter": "static-token-single-subject",
                "multi_user_isolation": False,
            },
            "access_scope": {
                "allowed_cities": list(context.allowed_cities),
                "allowed_metrics": list(context.allowed_metrics),
                "allowed_dataset_roles": list(context.allowed_dataset_roles),
                "max_time_range_hours": context.max_time_range_hours,
                "row_limit": context.row_limit,
                "export_policy": context.export_policy,
                "policy_snapshot_id": context.policy_snapshot_id,
                "access_scope_hash": context.scope_hash(),
            },
            "model_policy": {
                "endpoint_policy_id": context.model_endpoint_policy_id,
                "data_egress": context.model_data_egress,
                "intent_egress": context.model_intent_egress,
                "evidence_egress_allowed": AuthorizationService.may_send_evidence_to_model(
                    context, service.data_scope, endpoint_identity
                ),
                "intent_egress_allowed": AuthorizationService.may_send_intent_to_model(
                    context, service.data_scope, endpoint_identity
                ),
                "active_provider": endpoint_identity["provider"],
                "active_model": endpoint_identity.get("model") or None,
                "endpoint_target_hash": endpoint_identity["target_hash"],
                "endpoint_binding_verified": AuthorizationService.endpoint_matches(
                    context, endpoint_identity
                ),
            },
            "data_source": {
                "city": catalog_snapshot.get("city"),
                "source_version": catalog_snapshot.get("source_version"),
                "quality_status": catalog_snapshot.get("quality_status", "unknown"),
                "registration_status": catalog_snapshot.get("registration_status", "unknown"),
                "registration_quality_status": catalog_snapshot.get(
                    "registration_quality_status", "unknown"
                ),
                "runtime_quality_status": catalog_snapshot.get("runtime_quality_status", "unknown"),
                "freshness_status": catalog_snapshot.get("freshness_status", "unknown"),
                "quality_gate_evaluated_at": catalog_snapshot.get("quality_gate_evaluated_at"),
                "quality_gate": catalog_snapshot.get("quality_gate"),
                "access_policy": catalog_snapshot.get("access_policy"),
                "logical_registry_version": catalog_snapshot.get("logical_registry_version"),
                "logical_registry_hash": catalog_snapshot.get("logical_registry_hash"),
                "physical_mapping_version": catalog_snapshot.get("physical_mapping_version"),
                "physical_mapping_hash": catalog_snapshot.get("physical_mapping_hash"),
            },
            "promotion": {
                "gate_id": gate.gate_id,
                "configured_status": gate.configured_status,
                "enforced": service.data_scope != "synthetic",
                "ready": gate.ready,
                "runtime_flag_requested": runtime.production_assistant_enabled,
                "local_live_shadow_acknowledged": (runtime.local_live_shadow_acknowledged),
                "blockers": list(gate.blockers),
                "missing_owner_roles": list(gate.missing_owner_roles),
                "missing_thresholds": list(gate.missing_thresholds),
                "pending_artifacts": list(gate.pending_artifacts),
            },
            "tool_registry": {
                "registered_tools": assistant.tools.names,
                "tool_count": len(assistant.tools.names),
            },
        }

    @router.get(
        "/assistant/capabilities",
        response_model=AssistantCapabilities,
        tags=["assistant"],
    )
    def assistant_capabilities(
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        return assistant.capabilities(
            _resolved_access(access_context, application.state.access_context)
        )

    @router.get("/catalog", response_model=CatalogResponse, tags=["catalog"])
    def catalog(
        service: PassengerFlowDataService = Depends(_service),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        return service.catalog(_resolved_access(access_context, application.state.access_context))

    @router.post("/queries", response_model=QueryResponse, tags=["queries"])
    def query(
        payload: QueryRequest,
        service: PassengerFlowDataService = Depends(_service),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        return service.query(
            payload, _resolved_access(access_context, application.state.access_context)
        )

    @router.post("/forecasts/designated-day", response_model=ForecastResponse, tags=["forecasts"])
    def forecast(
        payload: ForecastRequest,
        service: PassengerFlowDataService = Depends(_service),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        return service.forecast(
            payload, _resolved_access(access_context, application.state.access_context)
        )

    @router.get("/audits/{audit_id}", response_model=AuditSummary, tags=["audits"])
    def audit(
        audit_id: str = Path(pattern=r"^(?:query|forecast)-[0-9a-f]{32}$"),
        service: PassengerFlowDataService = Depends(_service),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        try:
            return service.audit(
                audit_id, _resolved_access(access_context, application.state.access_context)
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="audit not found") from exc

    @router.post(
        "/assistant/sessions",
        response_model=SessionRecord,
        tags=["assistant"],
    )
    def create_assistant_session(
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        return assistant.create_session(
            _resolved_access(access_context, application.state.access_context)
        )

    @router.post(
        "/assistant/sessions/{session_id}/messages",
        response_model=RunRecord,
        tags=["assistant"],
    )
    def assistant_message(
        payload: AssistantMessageRequest,
        session_id: str = Path(pattern=r"^session-[0-9a-f]{32}$"),
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        try:
            return assistant.message(
                session_id,
                payload,
                _resolved_access(access_context, application.state.access_context),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="assistant session not found") from exc

    @router.get(
        "/assistant/runs/{run_id}",
        response_model=RunRecord,
        tags=["assistant"],
    )
    def assistant_run(
        run_id: str = Path(pattern=r"^run-[0-9a-f]{32}$"),
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        try:
            return assistant.get_run(
                run_id, _resolved_access(access_context, application.state.access_context)
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="assistant run not found") from exc

    @router.get(
        "/assistant/runs/{run_id}/events",
        response_model=list[dict],
        tags=["assistant"],
    )
    def assistant_events(
        run_id: str = Path(pattern=r"^run-[0-9a-f]{32}$"),
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> list[dict]:
        try:
            return assistant.get_events(
                run_id, _resolved_access(access_context, application.state.access_context)
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="assistant run not found") from exc

    @router.post(
        "/assistant/runs/{run_id}/feedback",
        response_model=RunRecord,
        tags=["assistant"],
    )
    def assistant_feedback(
        payload: HumanFeedbackRequest,
        run_id: str = Path(pattern=r"^run-[0-9a-f]{32}$"),
        assistant: AssistantService = Depends(_assistant),
        access_context: AccessContext = Depends(_authorize),
    ) -> dict:
        try:
            return assistant.record_feedback(
                run_id,
                payload,
                _resolved_access(access_context, application.state.access_context),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="assistant run not found") from exc

    application.include_router(router)
    return application


app = create_app()
