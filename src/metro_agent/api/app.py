from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metro_agent import __version__
from metro_agent.api.models import (
    AuditSummary,
    CatalogResponse,
    ForecastRequest,
    ForecastResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
)
from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.schemas import (
    AssistantMessageRequest,
    HumanFeedbackRequest,
    RunRecord,
    SessionRecord,
)

_bearer = HTTPBearer(auto_error=False)


def _service(request: Request) -> SyntheticApiService:
    return request.app.state.service


def _assistant(request: Request) -> AssistantService:
    return request.app.state.assistant


def _authorize(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    configured = request.app.state.settings.access_token
    if configured is None:
        return
    supplied = credentials.credentials if credentials and credentials.scheme == "Bearer" else ""
    if not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    runtime = settings or ApiSettings.from_env()
    application = FastAPI(
        title="Metro Passenger Flow API",
        summary="Synthetic-only mobile API for governed passenger-flow queries",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.settings = runtime
    application.state.service = SyntheticApiService(runtime)
    application.state.assistant = AssistantService(
        application.state.service,
        runtime.audit_dir.parent / "assistant",
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
    async def invalid_request_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": {"code": "invalid_request", "message": str(exc)}},
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
            "data_scope": "synthetic",
        }

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(_authorize)])

    @router.get("/catalog", response_model=CatalogResponse, tags=["catalog"])
    def catalog(service: SyntheticApiService = Depends(_service)) -> dict:
        return service.catalog()

    @router.post("/queries", response_model=QueryResponse, tags=["queries"])
    def query(payload: QueryRequest, service: SyntheticApiService = Depends(_service)) -> dict:
        return service.query(payload)

    @router.post("/forecasts/designated-day", response_model=ForecastResponse, tags=["forecasts"])
    def forecast(
        payload: ForecastRequest, service: SyntheticApiService = Depends(_service)
    ) -> dict:
        return service.forecast(payload)

    @router.get("/audits/{audit_id}", response_model=AuditSummary, tags=["audits"])
    def audit(
        audit_id: str = Path(pattern=r"^(?:query|forecast)-[0-9a-f]{32}$"),
        service: SyntheticApiService = Depends(_service),
    ) -> dict:
        try:
            return service.audit(audit_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="audit not found") from exc

    @router.post(
        "/assistant/sessions",
        response_model=SessionRecord,
        tags=["assistant"],
    )
    def create_assistant_session(
        assistant: AssistantService = Depends(_assistant),
    ) -> dict:
        return assistant.create_session()

    @router.post(
        "/assistant/sessions/{session_id}/messages",
        response_model=RunRecord,
        tags=["assistant"],
    )
    def assistant_message(
        payload: AssistantMessageRequest,
        session_id: str = Path(pattern=r"^session-[0-9a-f]{32}$"),
        assistant: AssistantService = Depends(_assistant),
    ) -> dict:
        try:
            return assistant.message(session_id, payload)
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
    ) -> dict:
        try:
            return assistant.get_run(run_id)
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
    ) -> list[dict]:
        try:
            return assistant.get_events(run_id)
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
    ) -> dict:
        try:
            return assistant.record_feedback(run_id, payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="assistant run not found") from exc

    application.include_router(router)
    return application


app = create_app()
