from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskType = Literal[
    "query",
    "compare",
    "forecast",
    "alert",
    "transfer",
    "geo",
    "correlation",
    "diagnosis",
    "trend",
    "report",
    "travel",
    "help",
    "general",
    "external",
]
OperationName = Literal[
    "list_entities",
    "describe_entity",
    "list_metrics",
    "list_available_dates",
    "summarize_dataset",
    "query_metric",
    "rank_entities",
    "compare_periods",
    "forecast",
    "alert",
    "transfer",
    "geo",
    "correlation",
    "diagnosis",
    "trend_analysis",
    "report",
    "capability_readiness",
    "travel_plan",
    "capability_help",
    "general_answer",
    "external_answer",
]
EntityType = Literal["station", "line", "direction", "date", "metric"]
AnswerPolicy = Literal[
    "deterministic_table",
    "deterministic_summary",
    "llm_synthesis",
    "llm_general",
    "llm_hybrid",
]
CompletenessPolicy = Literal["require_complete", "reject_if_truncated"]
FailureCategory = Literal[
    "material_ambiguity",
    "intent_unrecognized",
    "entity_not_found",
    "capability_gap",
    "query_ir_unsupported",
    "data_unavailable",
    "result_truncated",
    "tool_failure",
    "model_failure",
    "verification_failure",
    "authorization_failure",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SemanticRoute = Literal["data", "general", "hybrid", "external", "clarify"]
SemanticOperation = Literal[
    "discover",
    "describe",
    "query",
    "aggregate",
    "rank",
    "compare",
    "forecast",
    "diagnose",
    "explain",
    "travel",
    "help",
    "alert",
    "transfer",
    "geo",
    "correlate",
    "trend",
    "report",
]


class SemanticEntityMention(StrictModel):
    """A user-language entity mention; database identifiers are deliberately absent."""

    type: Literal["line", "station", "place", "event", "unknown"]
    raw_text: str = Field(min_length=1, max_length=200)
    role: Literal["subject", "origin", "destination", "context"] = "subject"
    reference: Literal["named", "collection", "deictic"] = "named"


class SemanticMetricMention(StrictModel):
    raw_text: str = Field(min_length=1, max_length=100)
    candidate_metrics: list[str] = Field(default_factory=list, max_length=8)
    resolution: Literal["exact", "candidate", "unspecified", "unresolved"] = "unspecified"


class SemanticTimeExpression(StrictModel):
    raw_text: str | None = Field(default=None, max_length=200)
    resolution: Literal["explicit", "default_allowed", "unspecified", "unresolved"] = (
        "unspecified"
    )


class SemanticFrame(StrictModel):
    """Open-language meaning compiled by GPT; it cannot contain SQL or physical IDs."""

    schema_version: Literal["1.0"] = "1.0"
    route: SemanticRoute
    goal: str = Field(min_length=1, max_length=800)
    operations: list[SemanticOperation] = Field(min_length=1, max_length=8)
    target_kind: Literal[
        "line",
        "station",
        "metric",
        "date",
        "dataset",
        "capability",
        "place",
        "event",
        "unspecified",
    ] = "unspecified"
    entity_mentions: list[SemanticEntityMention] = Field(default_factory=list, max_length=16)
    metric_mentions: list[SemanticMetricMention] = Field(default_factory=list, max_length=8)
    time_expression: SemanticTimeExpression = Field(default_factory=SemanticTimeExpression)
    evidence_requirements: list[
        Literal[
            "database_rows",
            "metric_definition",
            "general_knowledge",
            "external_live_data",
            "navigation",
        ]
    ] = Field(default_factory=list, max_length=8)
    defaults_allowed: bool = True
    inherit_context: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    material_missing_fields: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_clarification(self) -> SemanticFrame:
        if self.route == "clarify" and not self.material_missing_fields:
            raise ValueError("clarify route requires material_missing_fields")
        return self


class EntityCandidate(StrictModel):
    id: str
    name: str
    type: Literal["line", "station"]
    confidence: float = Field(ge=0, le=1)
    source: Literal["registered_catalog", "observed_database_entity"]


class EntityResolution(StrictModel):
    raw_text: str
    type: Literal["line", "station", "place", "event", "unknown"]
    role: Literal["subject", "origin", "destination", "context"] = "subject"
    reference: Literal["named", "collection", "deictic"] = "named"
    status: Literal["resolved", "ambiguous", "not_found", "not_applicable"]
    selected_id: str | None = None
    selected_name: str | None = None
    candidates: list[EntityCandidate] = Field(default_factory=list, max_length=20)


class MetricResolution(StrictModel):
    raw_text: str
    status: Literal["resolved", "ambiguous", "not_found", "defaulted"]
    selected_metric: str | None = None
    candidates: list[str] = Field(default_factory=list, max_length=20)


class SemanticMemory(StrictModel):
    current_entities: dict[str, list[str]] = Field(default_factory=dict)
    current_metric: str | None = None
    current_time_range: dict[str, str] = Field(default_factory=dict)
    last_operations: list[SemanticOperation] = Field(default_factory=list)
    last_route: SemanticRoute | None = None
    updated_at: str | None = None


class EntitySet(StrictModel):
    lines: list[str] = Field(default_factory=list)
    stations: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)


class EventSpec(StrictModel):
    event_name: str = "unspecified_event"
    venue: str | None = None
    attendance: int = Field(default=20_000, ge=0, le=200_000)
    target_date: str | None = None
    impacted_stations: list[str] = Field(default_factory=list)


class TransferAnalysisSpec(StrictModel):
    window_minutes: int = Field(default=30, ge=5, le=120)
    rail_scope: list[str] = Field(default_factory=list)
    bus_scope: list[str] = Field(default_factory=list)
    output_dimensions: list[str] = Field(default_factory=lambda: ["station"])


class TravelPlanSpec(StrictModel):
    origin: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    mode: Literal["public_transit", "driving", "walking"] = "public_transit"
    departure_time: str | None = Field(default=None, max_length=100)


class ActionPlan(StrictModel):
    severity: Literal["normal", "warning", "critical"]
    actions: list[str] = Field(default_factory=list)
    notification_candidates: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool = True


class OperationIR(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    operation: OperationName
    entity_type: EntityType | None = None
    metric: str | None = None
    scope: Literal[
        "approved_observation_window",
        "registered_catalog",
        "authoritative_master",
        "requested_query_scope",
        "external_navigation",
        "general_knowledge",
    ] = "requested_query_scope"
    time_range: dict[str, str] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    completeness_required: bool = True
    answer_policy: AnswerPolicy = "llm_synthesis"
    target_query: str | None = None
    origin: str | None = None
    destination: str | None = None
    travel_mode: Literal["public_transit", "driving", "walking"] | None = None
    departure_time: str | None = None
    route_confidence: Literal["high", "model_candidate"] = "high"


class CapabilityDefinition(StrictModel):
    id: str = Field(min_length=1)
    operations: list[OperationName] = Field(min_length=1)
    tools: list[str] = Field(min_length=1)
    entity_types: list[EntityType] = Field(default_factory=list)
    data_scopes: list[Literal["synthetic", "production-shadow", "production-readonly"]] = Field(
        min_length=1
    )
    required_slots: list[str] = Field(default_factory=list)
    optional_slots: list[str] = Field(default_factory=list)
    completeness_policy: CompletenessPolicy
    answer_policy: AnswerPolicy


class CapabilityMatch(StrictModel):
    status: Literal["matched", "missing_slots", "unavailable"]
    capability_id: str | None = None
    registry_version: str
    tools: list[str] = Field(default_factory=list)
    answer_policy: AnswerPolicy
    completeness_policy: CompletenessPolicy = "require_complete"
    missing_slots: list[str] = Field(default_factory=list)
    unavailable_tools: list[str] = Field(default_factory=list)


class CoverageEvidence(StrictModel):
    coverage_type: Literal[
        "unknown",
        "observed_window",
        "registered_catalog",
        "query_result",
        "derived_result",
        "capability_readiness",
        "external_navigation",
        "general_context",
    ] = "unknown"
    scope_label: str = "unknown"
    authoritative_master: bool = False
    time_range: dict[str, str] = Field(default_factory=dict)
    returned_count: int = Field(default=0, ge=0)
    matched_count: int | None = Field(default=None, ge=0)
    complete: bool = False
    truncated: bool = False
    city: str | None = None
    dataset_role: Literal["actual", "reference", "forecast"] | None = None
    source_version: str | None = None
    freshness_status: str | None = None


class IntentEnvelope(StrictModel):
    task_type: TaskType
    user_goal: str = Field(min_length=1)
    entities: EntitySet = Field(default_factory=EntitySet)
    metrics: list[str] = Field(default_factory=list)
    metric_version: str = "1.0.0"
    city: str | None = None
    dataset_role: Literal["actual", "reference", "forecast"] = "actual"
    source_version: str | None = None
    time_grain: Literal["source", "10m", "15m", "30m", "hour", "day"] = "source"
    time_scope: dict[str, Any] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    event_spec: EventSpec | None = None
    transfer_spec: TransferAnalysisSpec | None = None
    travel_spec: TravelPlanSpec | None = None


class ToolStep(StrictModel):
    step_id: str = Field(pattern=r"^s[1-9][0-9]*$")
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class TaskPlan(StrictModel):
    plan_id: str = Field(min_length=1)
    task_type: TaskType
    steps: list[ToolStep]
    expected_evidence: list[str] = Field(default_factory=list)
    answer_format: str = "analysis_with_charts"

    @model_validator(mode="after")
    def validate_graph(self) -> TaskPlan:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("task plan contains duplicate step ids")
        known: set[str] = set()
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(f"step {step.step_id} has unknown or forward dependencies")
            known.add(step.step_id)
        return self


class ToolResult(StrictModel):
    step_id: str
    tool: str
    status: Literal["success", "failed", "skipped"]
    summary: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    returned_row_count: int = Field(default=0, ge=0)
    matched_row_count: int | None = Field(default=None, ge=0)
    matched_count_unknown: bool = False
    complete: bool = True
    truncated: bool = False
    query_fingerprint: str | None = None
    logical_plan_hash: str | None = None
    result_hash: str | None = None
    source_step_ids: list[str] = Field(default_factory=list)
    calculation_method: str | None = None
    policy_snapshot_id: str | None = None
    access_scope_hash: str | None = None
    block_reason: str | None = None
    coverage: CoverageEvidence = Field(default_factory=CoverageEvidence)


class StructuredClaim(StrictModel):
    claim_type: Literal["metric_total", "result_row"]
    metric_id: str | None = None
    metric_version: str | None = None
    unit: str | None = None
    aggregation: str | None = None
    value: int | float | None = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, int | float] = Field(default_factory=dict)


class ResultFieldSpec(StrictModel):
    field: str = Field(min_length=1)
    type: Literal["boolean", "integer", "number", "null", "string"]


class EvidenceItem(StrictModel):
    evidence_id: str
    step_id: str
    kind: Literal["fact", "statistic", "chart", "model_output", "knowledge"]
    claim: str
    value: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    structured_claims: list[StructuredClaim] = Field(default_factory=list)
    result_schema: list[ResultFieldSpec] = Field(default_factory=list)
    returned_row_count: int = Field(default=0, ge=0)
    matched_row_count: int | None = Field(default=None, ge=0)
    matched_count_unknown: bool = False
    complete: bool = True
    truncated: bool = False
    query_fingerprint: str | None = None
    logical_plan_hash: str | None = None
    result_hash: str | None = None
    source_evidence_ids: list[str] = Field(default_factory=list)
    calculation_method: str | None = None
    policy_snapshot_id: str | None = None
    access_scope_hash: str | None = None
    warnings: list[str] = Field(default_factory=list)
    block_reason: str | None = None
    coverage: CoverageEvidence = Field(default_factory=CoverageEvidence)


class EvidencePacket(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    question: str
    facts: list[EvidenceItem] = Field(default_factory=list)
    statistics: list[EvidenceItem] = Field(default_factory=list)
    charts: list[EvidenceItem] = Field(default_factory=list)
    model_outputs: list[EvidenceItem] = Field(default_factory=list)
    knowledge_sources: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    def evidence_ids(self) -> set[str]:
        return {
            item.evidence_id
            for group in (
                self.facts,
                self.statistics,
                self.charts,
                self.model_outputs,
                self.knowledge_sources,
            )
            for item in group
        }


class AssistantResponse(StrictModel):
    answer: str
    key_findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


class VerificationReport(StrictModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    supported_evidence_refs: list[str] = Field(default_factory=list)


class DatasetEligibility(StrictModel):
    eligible: bool = False
    reasons: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool = True


class HumanFeedback(StrictModel):
    correction: str
    accepted: bool | None = None
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class HumanFeedbackRequest(StrictModel):
    correction: str = Field(min_length=1, max_length=4000)
    accepted: bool
    adopted_response: AssistantResponse | None = None


class AssistantMessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4000)


class ModelRuntime(StrictModel):
    provider: str = "unknown"
    model: str | None = None
    mode: Literal["offline_deterministic", "local_governed_model", "openai_compatible"] = (
        "offline_deterministic"
    )
    execution_role: Literal["deterministic_active", "model_active", "shadow_report_only"] = (
        "deterministic_active"
    )
    real_model_configured: bool = False
    real_model_active: bool = False
    invocation_status: Literal["not_applicable", "configured", "succeeded", "failed", "partial"] = (
        "not_applicable"
    )
    usage_reporting: Literal["not_applicable", "unavailable", "partial", "complete"] = (
        "not_applicable"
    )
    provider_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    elapsed_seconds: float | None = Field(default=None, ge=0)


class AssistantArchitectureStage(StrictModel):
    id: str
    label: str
    owner: Literal["llm", "deterministic", "human"]
    detail: str


class ValidationMilestone(StrictModel):
    id: str
    label: str
    status: Literal["verified", "partial", "not_started"]
    evidence: str
    scope: str


class AssistantCapabilities(StrictModel):
    implementation_status: Literal["local_governed_prototype"]
    data_scope: Literal["synthetic", "production-shadow", "production-readonly"]
    active_runtime: ModelRuntime
    architecture: list[AssistantArchitectureStage]
    model_responsibilities: list[str]
    deterministic_controls: list[str]
    prohibited_model_actions: list[str]
    validated_milestones: list[ValidationMilestone]
    production_gaps: list[str]
    capability_registry_version: str
    operation_capabilities: list[dict[str, Any]] = Field(default_factory=list)


class SessionRecord(StrictModel):
    session_id: str
    created_at: str
    owner_subject_id: str
    owner_tenant_or_department: str
    access_scope_hash: str
    policy_snapshot_id: str
    messages: list[dict[str, str]] = Field(default_factory=list)
    semantic_memory: SemanticMemory = Field(default_factory=SemanticMemory)


class ModelEgressRecord(StrictModel):
    call_id: str
    purpose: Literal["semantic_compile", "intent_candidate", "synthesis"]
    decision: Literal["denied", "approved"]
    endpoint_policy_id: str
    provider: str
    model: str | None = None
    endpoint_target_hash: str
    endpoint_binding_verified: bool
    exact_payload_hash: str
    outbound_field_paths: list[str] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None
    status: Literal["started", "succeeded", "failed", "not_called"]


class RunRecord(StrictModel):
    run_id: str
    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: Literal["running", "completed", "needs_clarification", "failed"] = "running"
    provider: str
    owner_subject_id: str
    owner_tenant_or_department: str
    access_scope_hash: str
    policy_snapshot_id: str
    intent_route: Literal[
        "deterministic",
        "model_candidate",
        "semantic_model",
        "semantic_fallback",
        "clarification",
    ] = "deterministic"
    planner_route: Literal["deterministic"] = "deterministic"
    model_egress: list[ModelEgressRecord] = Field(default_factory=list)
    model_runtime: ModelRuntime = Field(default_factory=ModelRuntime)
    original_question: str
    selected_context: dict[str, Any] = Field(default_factory=dict)
    semantic_frame: SemanticFrame | None = None
    semantic_source: Literal["model", "deterministic_fallback"] | None = None
    semantic_shadow_frame: SemanticFrame | None = None
    semantic_disagreements: list[str] = Field(default_factory=list)
    entity_resolutions: list[EntityResolution] = Field(default_factory=list)
    metric_resolutions: list[MetricResolution] = Field(default_factory=list)
    semantic_memory_snapshot: SemanticMemory = Field(default_factory=SemanticMemory)
    intent: IntentEnvelope | None = None
    operation_ir: OperationIR | None = None
    capability_match: CapabilityMatch | None = None
    failure_category: FailureCategory | None = None
    plan: TaskPlan | None = None
    replans: list[TaskPlan] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence: EvidencePacket | None = None
    response: AssistantResponse | None = None
    verification: VerificationReport | None = None
    human_feedback: list[HumanFeedback] = Field(default_factory=list)
    adopted_response: AssistantResponse | None = None
    dataset_eligibility: DatasetEligibility = Field(default_factory=DatasetEligibility)
    events: list[dict[str, Any]] = Field(default_factory=list)
