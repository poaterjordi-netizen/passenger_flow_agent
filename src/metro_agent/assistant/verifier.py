from __future__ import annotations

import math
import json
import re
from typing import Any

from metro_agent.assistant.schemas import (
    AssistantResponse,
    EvidencePacket,
    TaskPlan,
    VerificationReport,
)


def verify_plan(plan: TaskPlan, registered_tools: set[str]) -> None:
    if not plan.steps:
        raise ValueError("task plan must contain at least one tool step")
    unknown = sorted({step.tool for step in plan.steps} - registered_tools)
    if unknown:
        raise ValueError(f"task plan references unregistered tools: {', '.join(unknown)}")


def verify_response(response: AssistantResponse, evidence: EvidencePacket) -> VerificationReport:
    errors: list[str] = []
    warnings: list[str] = []
    known = evidence.evidence_ids()
    unknown = sorted(set(response.evidence_refs) - known)
    if unknown:
        errors.append(f"unknown evidence references: {', '.join(unknown)}")
    if known and not response.evidence_refs:
        errors.append("response does not cite available evidence")
    if evidence.missing_evidence:
        warnings.extend(evidence.missing_evidence)
    if not response.answer.strip():
        errors.append("answer is empty")
    if not _finite_numbers(response.model_dump(mode="json")):
        errors.append("response contains a non-finite number")
    unsupported_numbers = _unsupported_answer_numbers(response.answer, evidence)
    if unsupported_numbers:
        errors.append(
            f"answer contains numbers absent from evidence: {', '.join(unsupported_numbers)}"
        )
    return VerificationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        supported_evidence_refs=sorted(set(response.evidence_refs) & known),
    )


def _finite_numbers(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_numbers(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_numbers(item) for item in value)
    return True


def _unsupported_answer_numbers(answer: str, evidence: EvidencePacket) -> list[str]:
    numbers = set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", answer))
    if not numbers:
        return []
    serialized = json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    evidence_numbers = set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", serialized))
    return sorted(numbers - evidence_numbers)
