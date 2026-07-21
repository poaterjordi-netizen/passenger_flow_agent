from __future__ import annotations

import math
import json
import re
from datetime import datetime
from typing import Any

from metro_agent.access import AccessContext
from metro_agent.assistant.schemas import (
    AssistantResponse,
    EvidencePacket,
    IntentEnvelope,
    TaskPlan,
    ToolResult,
    VerificationReport,
)


def verify_evidence_packet(
    evidence: EvidencePacket,
    results: list[ToolResult],
    access_context: AccessContext,
) -> None:
    """Verify packet hashes, lineage, completeness, and authorization binding."""

    if evidence.missing_evidence:
        raise ValueError("evidence packet is missing required tool evidence")
    items = _evidence_items(evidence)
    by_step = {item.step_id: item for item in items}
    if len(by_step) != len(items):
        raise ValueError("evidence packet contains duplicate step lineage")
    successful = [item for item in results if item.status == "success"]
    if set(by_step) != {item.step_id for item in successful}:
        raise ValueError("evidence packet does not match successful tool results")
    scope_hash = access_context.scope_hash()
    for result in successful:
        item = by_step[result.step_id]
        expected_hash = _hash_result(result.summary, result.rows)
        if result.result_hash != expected_hash or item.result_hash != expected_hash:
            raise ValueError("evidence result hash verification failed")
        expected_sources = {f"ev-{step_id}" for step_id in result.source_step_ids}
        if set(item.source_evidence_ids) != expected_sources:
            raise ValueError("evidence lineage does not match tool dependencies")
        if result.policy_snapshot_id != access_context.policy_snapshot_id:
            raise PermissionError("tool result policy snapshot does not match the run")
        if item.policy_snapshot_id != access_context.policy_snapshot_id:
            raise PermissionError("evidence policy snapshot does not match the run")
        if result.access_scope_hash != scope_hash or item.access_scope_hash != scope_hash:
            raise PermissionError("evidence access scope does not match the run")
        if result.complete is False or result.truncated:
            raise ValueError("incomplete tool result cannot become assistant evidence")
        if item.complete is False or item.truncated:
            raise ValueError("incomplete evidence cannot support an assistant answer")
        if item.coverage != result.coverage:
            raise ValueError("evidence coverage does not match the tool result")
        if item.coverage.returned_count != result.returned_row_count:
            raise ValueError("coverage returned count does not match the tool result")
        if item.coverage.matched_count != result.matched_row_count:
            raise ValueError("coverage matched count does not match the tool result")
        if item.coverage.complete != result.complete:
            raise ValueError("coverage completeness does not match the tool result")
        if item.coverage.truncated != result.truncated:
            raise ValueError("coverage truncation does not match the tool result")
    known = evidence.evidence_ids()
    if any(source not in known for item in items for source in item.source_evidence_ids):
        raise ValueError("evidence lineage references an unknown source")
    _verify_acyclic_lineage(items)


def verify_intent(intent: IntentEnvelope, protected_reference: IntentEnvelope) -> None:
    fields = (
        "task_type",
        "entities",
        "metrics",
        "metric_version",
        "city",
        "dataset_role",
        "source_version",
        "time_grain",
        "time_scope",
        "ambiguities",
        "needs_clarification",
        "event_spec",
        "transfer_spec",
        "travel_spec",
    )
    drifted = [
        field for field in fields if getattr(intent, field) != getattr(protected_reference, field)
    ]
    if drifted:
        raise ValueError(f"intent drifted from protected reference: {', '.join(drifted)}")


def verify_candidate_intent(
    intent: IntentEnvelope, catalog: dict[str, Any], access_context: AccessContext
) -> None:
    """Hard-validate a deterministic or model-proposed intent without exact-match coupling."""

    metric_versions = {
        item["id"]: item.get("version", "1.0.0") for item in catalog.get("metrics", [])
    }
    unknown_metrics = sorted(set(intent.metrics) - set(metric_versions))
    if unknown_metrics:
        raise ValueError(f"intent contains unknown metrics: {', '.join(unknown_metrics)}")
    if any(metric not in access_context.allowed_metrics for metric in intent.metrics):
        raise PermissionError("intent metric is outside the authorized scope")
    if any(metric_versions[metric] != intent.metric_version for metric in intent.metrics):
        raise ValueError("intent metric version does not match the catalog")
    if intent.city not in access_context.allowed_cities:
        raise PermissionError("intent city is outside the authorized scope")
    if intent.city != catalog.get("city"):
        raise ValueError("intent city does not match the selected catalog")
    if intent.dataset_role not in access_context.allowed_dataset_roles:
        raise PermissionError("intent dataset role is outside the authorized scope")
    if intent.source_version != catalog.get("source_version"):
        raise ValueError("intent source version does not match the selected catalog")
    available_lines = set(catalog.get("lines", []))
    available_stations = set(catalog.get("stations", []))
    if set(intent.entities.lines) - available_lines:
        raise ValueError("intent contains an entity outside the catalog")
    if set(intent.entities.stations) - available_stations:
        raise ValueError("intent contains an entity outside the catalog")
    resolved = intent.time_scope.get("resolved_range")
    if resolved:
        if not isinstance(resolved, dict) or set(resolved) != {"start", "end"}:
            raise ValueError("intent resolved time range is invalid")
        start = datetime.fromisoformat(str(resolved["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(resolved["end"]).replace("Z", "+00:00"))
        if start >= end:
            raise ValueError("intent resolved time range is not ordered")
        if (end - start).total_seconds() > access_context.max_time_range_hours * 3600:
            raise PermissionError("intent time range exceeds the authorized scope")


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


def verify_response(
    response: AssistantResponse,
    evidence: EvidencePacket,
    *,
    allow_general_knowledge: bool = False,
) -> VerificationReport:
    errors: list[str] = []
    warnings: list[str] = []
    known = evidence.evidence_ids()
    unknown = sorted(set(response.evidence_refs) - known)
    if unknown:
        errors.append(f"unknown evidence references: {', '.join(unknown)}")
    if known and not response.evidence_refs:
        errors.append("response does not cite available evidence")
    if evidence.missing_evidence:
        errors.extend(evidence.missing_evidence)
    for item in _evidence_items(evidence):
        quality = item.metadata.get("quality_status")
        freshness = item.metadata.get("freshness_status")
        if item.block_reason:
            errors.append(f"blocked evidence: {item.evidence_id}")
        if (item.truncated or not item.complete) and item.evidence_id in response.evidence_refs:
            errors.append(f"cited evidence is incomplete: {item.evidence_id}")
        if any(source not in known for source in item.source_evidence_ids):
            errors.append(f"unknown evidence lineage source: {item.evidence_id}")
        if quality == "blocked":
            errors.append(f"blocked data quality in evidence: {item.evidence_id}")
        elif quality == "warning":
            warnings.append(f"data quality warning in evidence: {item.evidence_id}")
        if freshness == "stale":
            warnings.append(f"stale evidence: {item.evidence_id}")
        elif freshness == "unknown":
            warnings.append(f"evidence freshness is unknown: {item.evidence_id}")
    if not response.answer.strip():
        errors.append("answer is empty")
    if not _finite_numbers(response.model_dump(mode="json")):
        errors.append("response contains a non-finite number")
    if allow_general_knowledge:
        warnings.append("general knowledge answer is not grounded in metroflow database rows")
    else:
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


def _hash_result(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        {"summary": summary, "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    import hashlib

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_acyclic_lineage(items: list[Any]) -> None:
    sources = {item.evidence_id: set(item.source_evidence_ids) for item in items}

    def visit(evidence_id: str, path: set[str]) -> None:
        if evidence_id in path:
            raise ValueError("evidence lineage contains a cycle")
        for source in sources.get(evidence_id, set()):
            visit(source, {*path, evidence_id})

    for evidence_id in sources:
        visit(evidence_id, set())


NUMBER_PATTERN = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
ANCHOR_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}")
CLAIM_SPLIT_PATTERN = re.compile(
    r"[；;。！？\n，、：:]|,(?!\d)|"
    r"(?<=\d)\s*(?:和|与|及)\s*(?=[A-Za-z\u4e00-\u9fff])|"
    r"(?<=人次)\s*(?:和|与|及)\s*(?=\d)"
)
TRACE_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:s\d+|ev-s\d+|run-[0-9a-f]+|query-[0-9a-f]+)(?![A-Za-z0-9])"
)
SEMANTIC_DIMENSION_KEYS = {
    "destination",
    "direction",
    "group",
    "line",
    "origin",
    "period",
    "region",
    "station",
    "time",
}


def _unsupported_response_numbers(
    response: AssistantResponse, evidence: EvidencePacket
) -> list[str]:
    cited = set(response.evidence_refs)
    evidence_fragments: dict[str, list[str]] = {}
    evidence_entities: dict[str, set[str]] = {}
    for item in _evidence_items(evidence):
        if item.evidence_id not in cited:
            continue
        evidence_fragments[item.evidence_id] = _evidence_fragments(
            item.claim,
            {"structured_claims": item.structured_claims, "display_value": item.value},
        )
        evidence_entities[item.evidence_id] = _semantic_entities(item)
    all_entities = set().union(*evidence_entities.values()) if evidence_entities else set()
    unsupported: set[str] = set()
    for segment, evidence_hint in _response_segments(response):
        numbers = _numbers(segment)
        if not numbers:
            continue
        anchors = set(ANCHOR_PATTERN.findall(NUMBER_PATTERN.sub(" ", segment)))
        identifiers = {anchor for anchor in anchors if anchor[0].isascii()}
        mentioned_entities = {
            entity for entity in all_entities if _contains_entity(segment, entity)
        }
        supported = False
        candidate_ids = (
            [evidence_hint]
            if evidence_hint is not None and evidence_hint in evidence_fragments
            else list(evidence_fragments)
        )
        for evidence_id in candidate_ids:
            if mentioned_entities and not mentioned_entities.issubset(
                evidence_entities[evidence_id]
            ):
                continue
            for fragment in evidence_fragments[evidence_id]:
                if not numbers.issubset(_numbers(fragment)):
                    continue
                fragment_anchors = set(ANCHOR_PATTERN.findall(NUMBER_PATTERN.sub(" ", fragment)))
                fragment_identifiers = {
                    anchor for anchor in fragment_anchors if anchor[0].isascii()
                }
                if (
                    evidence_hint is None
                    and identifiers
                    and not identifiers.issubset(fragment_identifiers)
                ):
                    continue
                if mentioned_entities and not all(
                    _contains_entity(fragment, entity) for entity in mentioned_entities
                ):
                    continue
                supported = True
                break
            if supported:
                break

        # Dates, time ranges, row counts and totals may be represented by several
        # scalar fields in one evidence item.  Allow their union only when the
        # response segment does not name a semantic entity.  Entity/value pairs
        # must match one fragment above, preventing station-number swaps.
        if not supported and not mentioned_entities:
            for evidence_id in candidate_ids:
                fragments = evidence_fragments[evidence_id]
                available_numbers = set().union(*(_numbers(value) for value in fragments))
                if not numbers.issubset(available_numbers):
                    continue
                available_identifiers = set().union(
                    *(
                        {
                            anchor
                            for anchor in ANCHOR_PATTERN.findall(NUMBER_PATTERN.sub(" ", fragment))
                            if anchor[0].isascii()
                        }
                        for fragment in fragments
                    )
                )
                if (
                    evidence_hint is None
                    and identifiers
                    and not identifiers.issubset(available_identifiers)
                ):
                    continue
                supported = True
                break
        if not supported:
            unsupported.update(numbers)
    return sorted(unsupported)


def _numbers(text: str) -> set[str]:
    numbers: set[str] = set()
    for match in NUMBER_PATTERN.finditer(text):
        value = match.group(0).replace(",", "")
        # In ISO dates the separator before a component is not a minus sign.
        if value.startswith(("-", "+")) and match.start() > 0 and text[match.start() - 1].isdigit():
            value = value[1:]
        numbers.add(value)
    return numbers


def _semantic_entities(item: Any) -> set[str]:
    entities: set[str] = set()
    for claim in item.structured_claims:
        for value in claim.dimensions.values():
            if isinstance(value, str) and value:
                entities.add(value)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            entities.update(
                child
                for key, child in value.items()
                if key in SEMANTIC_DIMENSION_KEYS and isinstance(child, str) and child
            )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(item.value)
    return entities


def _contains_entity(text: str, entity: str) -> bool:
    if not entity:
        return False
    if entity.isascii() and entity.isalnum():
        pattern = rf"(?<![A-Za-z0-9]){re.escape(entity)}(?![A-Za-z0-9])"
        return re.search(pattern, text) is not None
    return entity in text


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
        (TRACE_IDENTIFIER_PATTERN.sub("", segment.strip()), None)
        for text in text_fields
        for segment in CLAIM_SPLIT_PATTERN.split(text)
        if segment.strip()
    ]

    def visit_chart(item: Any, context: str, evidence_hint: str | None) -> None:
        if isinstance(item, dict):
            scalar_context = " ".join(
                f"{key}={value}"
                for key, value in item.items()
                if key not in {"artifact_refs", "evidence_id"}
                if not isinstance(value, (dict, list)) and not isinstance(value, (int, float))
            )
            for key, value in item.items():
                if key in {"artifact_refs", "evidence_id"}:
                    continue
                visit_chart(
                    value,
                    f"{context} {scalar_context} {key}".strip(),
                    evidence_hint,
                )
        elif isinstance(item, list):
            for value in item:
                visit_chart(value, context, evidence_hint)
        elif isinstance(item, (int, float)):
            segments.append((TRACE_IDENTIFIER_PATTERN.sub("", f"{context} {item}"), evidence_hint))
        elif isinstance(item, str) and NUMBER_PATTERN.search(item):
            segments.append((TRACE_IDENTIFIER_PATTERN.sub("", f"{context} {item}"), evidence_hint))

    for chart in response.charts:
        evidence_hint = chart.get("evidence_id")
        visit_chart(
            chart,
            "chart",
            evidence_hint if isinstance(evidence_hint, str) else None,
        )
    return segments
