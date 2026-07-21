from __future__ import annotations

import math
import json
import re
from typing import Any

from metro_agent.assistant.schemas import (
    AssistantResponse,
    EvidencePacket,
    IntentEnvelope,
    TaskPlan,
    VerificationReport,
)


def verify_intent(intent: IntentEnvelope, protected_reference: IntentEnvelope) -> None:
    fields = (
        "task_type",
        "entities",
        "metrics",
        "time_scope",
        "ambiguities",
        "needs_clarification",
        "event_spec",
        "transfer_spec",
    )
    drifted = [
        field for field in fields if getattr(intent, field) != getattr(protected_reference, field)
    ]
    if drifted:
        raise ValueError(f"intent drifted from protected reference: {', '.join(drifted)}")


def verify_plan(
    plan: TaskPlan,
    registered_tools: set[str],
    protected_reference: TaskPlan | None = None,
) -> None:
    if not plan.steps:
        raise ValueError("task plan must contain at least one tool step")
    unknown = sorted({step.tool for step in plan.steps} - registered_tools)
    if unknown:
        raise ValueError(f"task plan references unregistered tools: {', '.join(unknown)}")
    if protected_reference is not None:
        fields = ("task_type", "steps", "expected_evidence", "answer_format")
        drifted = [
            field for field in fields if getattr(plan, field) != getattr(protected_reference, field)
        ]
        if drifted:
            raise ValueError(f"task plan drifted from protected reference: {', '.join(drifted)}")


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
    unsupported_numbers = _unsupported_response_numbers(response, evidence)
    if unsupported_numbers:
        errors.append(
            "response contains numbers without cited semantic evidence: "
            f"{', '.join(unsupported_numbers)}"
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


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
ANCHOR_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}")
CLAIM_SPLIT_PATTERN = re.compile(
    r"[；;。！？\n，]|,(?!\d)|(?<=\d)\s*(?:和|与|及)\s*(?=[A-Za-z\u4e00-\u9fff])"
)


def _unsupported_response_numbers(
    response: AssistantResponse, evidence: EvidencePacket
) -> list[str]:
    cited = set(response.evidence_refs)
    fragments = [
        (item.evidence_id, fragment)
        for item in _evidence_items(evidence)
        if item.evidence_id in cited
        for fragment in _evidence_fragments(item.claim, item.value)
    ]
    unsupported: set[str] = set()
    for segment, evidence_hint in _response_segments(response):
        numbers = set(NUMBER_PATTERN.findall(segment))
        if not numbers:
            continue
        anchors = set(ANCHOR_PATTERN.findall(NUMBER_PATTERN.sub(" ", segment)))
        identifiers = {anchor for anchor in anchors if anchor[0].isascii()}
        supported = False
        for evidence_id, fragment in fragments:
            if evidence_hint is not None and evidence_id != evidence_hint:
                continue
            if not numbers.issubset(set(NUMBER_PATTERN.findall(fragment))):
                continue
            fragment_anchors = set(ANCHOR_PATTERN.findall(NUMBER_PATTERN.sub(" ", fragment)))
            if evidence_hint is None:
                fragment_identifiers = {
                    anchor for anchor in fragment_anchors if anchor[0].isascii()
                }
                if identifiers and not identifiers.issubset(fragment_identifiers):
                    continue
                if anchors and not anchors.intersection(fragment_anchors):
                    continue
            supported = True
            break
        if not supported:
            unsupported.update(numbers)
    return sorted(unsupported)


def _evidence_items(evidence: EvidencePacket) -> list[Any]:
    return [
        item
        for group in (
            evidence.facts,
            evidence.statistics,
            evidence.charts,
            evidence.model_outputs,
            evidence.knowledge_sources,
        )
        for item in group
    ]


def _evidence_fragments(claim: str, value: Any) -> list[str]:
    fragments = [claim]

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if all(not isinstance(child, (dict, list)) for child in item.values()):
                fragments.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
            for key, child in item.items():
                if not isinstance(child, (dict, list)):
                    fragments.append(f"{key}={child}")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            fragments.append(item)

    visit(value)
    return fragments


def _response_segments(response: AssistantResponse) -> list[tuple[str, str | None]]:
    text_fields = [
        response.answer,
        *response.key_findings,
        *response.recommendations,
        *response.assumptions,
        *response.limitations,
        *response.follow_up_questions,
    ]
    segments: list[tuple[str, str | None]] = [
        (segment.strip(), None)
        for text in text_fields
        for segment in CLAIM_SPLIT_PATTERN.split(text)
        if segment.strip()
    ]

    def visit_chart(item: Any, context: str, evidence_hint: str | None) -> None:
        if isinstance(item, dict):
            scalar_context = " ".join(
                f"{key}={value}"
                for key, value in item.items()
                if not isinstance(value, (dict, list)) and not isinstance(value, (int, float))
            )
            for key, value in item.items():
                visit_chart(
                    value,
                    f"{context} {scalar_context} {key}".strip(),
                    evidence_hint,
                )
        elif isinstance(item, list):
            for value in item:
                visit_chart(value, context, evidence_hint)
        elif isinstance(item, (int, float)):
            segments.append((f"{context} {item}", evidence_hint))
        elif isinstance(item, str) and NUMBER_PATTERN.search(item):
            segments.append((f"{context} {item}", evidence_hint))

    for chart in response.charts:
        evidence_hint = chart.get("evidence_id")
        visit_chart(
            chart,
            "chart",
            evidence_hint if isinstance(evidence_hint, str) else None,
        )
    return segments
