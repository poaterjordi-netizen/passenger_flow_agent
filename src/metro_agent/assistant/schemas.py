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
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class ActionPlan(StrictModel):
    severity: Literal["normal", "warning", "critical"]
    actions: list[str] = Field(default_factory=list)
    notification_candidates: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool = True


class IntentEnvelope(StrictModel):
    task_type: TaskType
    user_goal: str = Field(min_length=1)
    entities: EntitySet = Field(default_factory=EntitySet)
    metrics: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    event_spec: EventSpec | None = None
    transfer_spec: TransferAnalysisSpec | None = None


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


class EvidenceItem(StrictModel):
    evidence_id: str
    step_id: str
    kind: Literal["fact", "statistic", "chart", "model_output", "knowledge"]
    claim: str
    value: Any = None


class EvidencePacket(StrictModel):
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


class SessionRecord(StrictModel):
    session_id: str
    created_at: str
    messages: list[dict[str, str]] = Field(default_factory=list)


class RunRecord(StrictModel):
    run_id: str
    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: Literal["running", "completed", "needs_clarification", "failed"] = "running"
    provider: str
    original_question: str
    selected_context: dict[str, Any] = Field(default_factory=dict)
    intent: IntentEnvelope | None = None
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
