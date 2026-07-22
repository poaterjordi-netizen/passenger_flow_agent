from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from metro_agent.access import AccessContext
from metro_agent.api.models import QueryRequest
from metro_agent.api.service import PassengerFlowDataService
from metro_agent.assistant.schemas import (
    EntityCandidate,
    EntityResolution,
    EntitySet,
    IntentEnvelope,
    MetricResolution,
    SemanticEntityMention,
    SemanticFrame,
    SemanticMemory,
    SemanticMetricMention,
    SemanticTimeExpression,
    TravelPlanSpec,
)
from metro_agent.assistant.text_normalization import entity_match_keys, normalize_user_question


def validate_and_normalize_frame(frame: SemanticFrame, question: str) -> SemanticFrame:
    """Validate model meaning and add server-owned evidence requirements."""

    normalized_question = _compact(normalize_user_question(question))
    if not frame.inherit_context:
        invented = [
            mention.raw_text
            for mention in frame.entity_mentions
            if _compact(normalize_user_question(mention.raw_text)) not in normalized_question
        ]
        if invented:
            raise ValueError("semantic frame invented entity text not present in the question")

    evidence = list(frame.evidence_requirements)
    required = {
        "data": ("database_rows",),
        "general": ("general_knowledge",),
        "hybrid": ("database_rows", "general_knowledge"),
        "external": (
            "navigation" if "travel" in frame.operations else "external_live_data",
        ),
        "clarify": (),
    }[frame.route]
    for item in required:
        if item not in evidence:
            evidence.append(item)
    return frame.model_copy(update={"evidence_requirements": evidence})


def reconcile_material_semantics(
    primary: SemanticFrame, protected_shadow: SemanticFrame
) -> SemanticFrame:
    """Prevent a model from weakening an explicit diagnostic request to comparison only."""

    if "diagnose" in protected_shadow.operations and (
        "diagnose" not in primary.operations or primary.route not in {"data", "hybrid"}
    ):
        operations = [
            "diagnose",
            *(item for item in primary.operations if item not in {"compare", "diagnose"}),
        ]
        route = "hybrid" if primary.route == "hybrid" else protected_shadow.route
        return primary.model_copy(update={"route": route, "operations": operations})
    return primary


def fallback_semantic_frame(question: str, intent: IntentEnvelope) -> SemanticFrame:
    """Translate the legacy deterministic parser into an explicit fallback frame."""

    route = (
        "clarify"
        if intent.needs_clarification
        else "general"
        if intent.task_type in {"general", "help"}
        else "external"
        if intent.task_type in {"travel", "external"}
        else "data"
    )
    operation = {
        "query": _fallback_query_operation(question),
        "compare": "compare",
        "forecast": "forecast",
        "alert": "alert",
        "transfer": "transfer",
        "geo": "geo",
        "correlation": "correlate",
        "diagnosis": "diagnose",
        "trend": "trend",
        "report": "report",
        "travel": "travel",
        "help": "help",
        "general": "explain",
        "external": "explain",
    }[intent.task_type]
    target_kind = _fallback_target_kind(question, intent, operation)
    if target_kind in {"metric", "date"} and intent.task_type in {"general", "query"}:
        route, operation = "data", "discover"
    elif target_kind == "dataset" and any(
        token in question for token in ("基本情况", "概况", "数据范围", "有什么数据", "数据质量")
    ):
        route, operation = "data", "describe"
    mentions: list[SemanticEntityMention] = []
    normalized = normalize_user_question(question)
    line_texts = re.findall(
        r"(?:北京地铁)?\d+号线|(?<![A-Za-z0-9-])L[-_A-Za-z0-9]+",
        normalized,
    )
    resolved_line_values = list(intent.entities.lines)
    mention_values = line_texts or resolved_line_values
    for mention_value in mention_values:
        mentions.append(
            SemanticEntityMention(
                type="line",
                raw_text=mention_value,
            )
        )
    for station in intent.entities.stations:
        mentions.append(SemanticEntityMention(type="station", raw_text=station))
    if intent.travel_spec:
        if intent.travel_spec.origin:
            mentions.append(
                SemanticEntityMention(
                    type="place", raw_text=intent.travel_spec.origin, role="origin"
                )
            )
        if intent.travel_spec.destination:
            mentions.append(
                SemanticEntityMention(
                    type="place",
                    raw_text=intent.travel_spec.destination,
                    role="destination",
                )
            )
    if intent.event_spec:
        if intent.event_spec.venue:
            mentions.append(
                SemanticEntityMention(type="place", raw_text=intent.event_spec.venue)
            )
        mentions.append(
            SemanticEntityMention(type="event", raw_text=intent.event_spec.event_name)
        )
    metric_mentions = [
        SemanticMetricMention(raw_text=metric, candidate_metrics=[metric], resolution="exact")
        for metric in intent.metrics
    ]
    return SemanticFrame(
        route=route,
        goal=intent.user_goal,
        operations=[operation],
        target_kind=target_kind,
        entity_mentions=mentions,
        metric_mentions=metric_mentions,
        time_expression=SemanticTimeExpression(
            raw_text=_fallback_time_text(question),
            resolution=(
                "explicit" if _fallback_time_text(question) is not None else "default_allowed"
            ),
        ),
        evidence_requirements=(
            ["database_rows"]
            if route == "data"
            else ["general_knowledge"]
            if route == "general"
            else ["navigation"]
            if route == "external" and operation == "travel"
            else ["external_live_data"]
            if route == "external"
            else []
        ),
        defaults_allowed=True,
        material_missing_fields=list(intent.ambiguities),
        confidence=0.82 if not intent.needs_clarification else 0.55,
    )


def compare_semantic_frames(primary: SemanticFrame, shadow: SemanticFrame) -> list[str]:
    differences: list[str] = []
    if primary.route != shadow.route:
        differences.append(f"route:{shadow.route}->{primary.route}")
    if set(primary.operations) != set(shadow.operations):
        differences.append(
            "operations:"
            + ",".join(shadow.operations)
            + "->"
            + ",".join(primary.operations)
        )
    primary_types = sorted(item.type for item in primary.entity_mentions)
    shadow_types = sorted(item.type for item in shadow.entity_mentions)
    if primary_types != shadow_types:
        differences.append(
            f"entity_types:{','.join(shadow_types) or '-'}->{','.join(primary_types) or '-'}"
        )
    if bool(primary.material_missing_fields) != bool(shadow.material_missing_fields):
        differences.append("material_missing_fields changed")
    return differences


def resolve_entities(
    frame: SemanticFrame,
    data_service: PassengerFlowDataService,
    catalog: dict[str, Any],
    access_context: AccessContext,
) -> list[EntityResolution]:
    resolutions: list[EntityResolution] = []
    observed: dict[str, list[EntityCandidate]] = {}
    for mention in frame.entity_mentions:
        if mention.type not in {"line", "station"} or mention.reference != "named":
            resolutions.append(
                EntityResolution(
                    raw_text=mention.raw_text,
                    type=mention.type,
                    role=mention.role,
                    reference=mention.reference,
                    status="not_applicable",
                )
            )
            continue
        entity_type = mention.type
        if entity_type not in observed:
            observed[entity_type] = _entity_candidates(
                data_service, catalog, access_context, entity_type
            )
        candidates = _match_candidates(mention.raw_text, entity_type, observed[entity_type])
        if not candidates:
            resolutions.append(
                EntityResolution(
                    raw_text=mention.raw_text,
                    type=entity_type,
                    role=mention.role,
                    reference=mention.reference,
                    status="not_found",
                )
            )
            continue
        best = candidates[0].confidence
        tied = [item for item in candidates if best - item.confidence < 0.03]
        if len(tied) > 1:
            resolutions.append(
                EntityResolution(
                    raw_text=mention.raw_text,
                    type=entity_type,
                    role=mention.role,
                    reference=mention.reference,
                    status="ambiguous",
                    candidates=candidates,
                )
            )
            continue
        selected = candidates[0]
        resolutions.append(
            EntityResolution(
                raw_text=mention.raw_text,
                type=entity_type,
                role=mention.role,
                reference=mention.reference,
                status="resolved",
                selected_id=selected.id,
                selected_name=selected.name,
                candidates=candidates,
            )
        )
    return resolutions


def resolve_metrics(
    frame: SemanticFrame,
    catalog: dict[str, Any],
    memory: SemanticMemory,
) -> list[MetricResolution]:
    registered = {
        str(item.get("id")): item for item in catalog.get("metrics", []) if item.get("id")
    }
    resolutions: list[MetricResolution] = []
    for mention in frame.metric_mentions:
        allowed_candidates = [
            value for value in mention.candidate_metrics if value in registered
        ]
        raw_key = _compact(mention.raw_text)
        label_matches = [
            metric_id
            for metric_id, item in registered.items()
            if raw_key
            and raw_key
            in {
                _compact(metric_id),
                _compact(str(item.get("label") or "")),
            }
        ]
        candidates = list(dict.fromkeys([*allowed_candidates, *label_matches]))
        if len(candidates) == 1:
            resolutions.append(
                MetricResolution(
                    raw_text=mention.raw_text,
                    status="resolved",
                    selected_metric=candidates[0],
                    candidates=candidates,
                )
            )
        elif len(candidates) > 1 and frame.defaults_allowed and "entries" in candidates:
            resolutions.append(
                MetricResolution(
                    raw_text=mention.raw_text,
                    status="defaulted",
                    selected_metric="entries",
                    candidates=candidates,
                )
            )
        else:
            resolutions.append(
                MetricResolution(
                    raw_text=mention.raw_text,
                    status="ambiguous" if candidates else "not_found",
                    candidates=candidates,
                )
            )
    if not resolutions and frame.route in {"data", "hybrid"}:
        inherited = memory.current_metric if frame.inherit_context else None
        selected = inherited if inherited in registered else "entries" if "entries" in registered else None
        resolutions.append(
            MetricResolution(
                raw_text="会话继承指标" if inherited else "系统默认指标",
                status="defaulted" if selected else "not_found",
                selected_metric=selected,
                candidates=[selected] if selected else [],
            )
        )
    return resolutions


def intent_from_semantics(
    frame: SemanticFrame,
    fallback: IntentEnvelope,
    entity_resolutions: list[EntityResolution],
    metric_resolutions: list[MetricResolution],
    memory: SemanticMemory,
) -> IntentEnvelope:
    task_type = _task_type(frame)
    lines = [
        item.selected_id
        for item in entity_resolutions
        if item.type == "line" and item.status == "resolved" and item.selected_id
    ]
    stations = [
        item.selected_id
        for item in entity_resolutions
        if item.type == "station" and item.status == "resolved" and item.selected_id
    ]
    if frame.inherit_context:
        if not lines:
            lines = list(memory.current_entities.get("line", []))
        if not stations:
            stations = list(memory.current_entities.get("station", []))
    metrics = [
        item.selected_metric
        for item in metric_resolutions
        if item.selected_metric is not None
    ]
    issues = list(frame.material_missing_fields) if frame.route == "clarify" else []
    if frame.route in {"data", "hybrid"}:
        for item in entity_resolutions:
            if item.status == "ambiguous":
                issues.append(f"实体“{item.raw_text}”匹配到多个相近候选。")
            elif item.status == "not_found":
                issues.append(f"当前准入数据库时间窗没有观测到实体“{item.raw_text}”。")
        for item in metric_resolutions:
            if item.status == "ambiguous":
                issues.append(f"指标“{item.raw_text}”存在多个候选，且默认值不足以消歧。")
            elif item.status == "not_found":
                issues.append(f"指标“{item.raw_text}”不在已登记指标目录中。")

    place_mentions = {item.role: item.raw_text for item in frame.entity_mentions if item.type == "place"}
    travel_spec = fallback.travel_spec
    if task_type == "travel":
        travel_spec = TravelPlanSpec(
            origin=place_mentions.get("origin") or (travel_spec.origin if travel_spec else None),
            destination=place_mentions.get("destination")
            or (travel_spec.destination if travel_spec else None),
            city=travel_spec.city if travel_spec else fallback.city,
            mode=travel_spec.mode if travel_spec else "public_transit",
            departure_time=travel_spec.departure_time if travel_spec else None,
        )
    return fallback.model_copy(
        update={
            "task_type": task_type,
            "user_goal": frame.goal,
            "entities": EntitySet(
                lines=list(dict.fromkeys(lines)),
                stations=list(dict.fromkeys(stations)),
                directions=fallback.entities.directions,
                groups=fallback.entities.groups,
            ),
            "metrics": list(dict.fromkeys(metrics)),
            "ambiguities": list(dict.fromkeys(issues)),
            "needs_clarification": frame.route == "clarify" or bool(issues),
            "travel_spec": travel_spec,
        }
    )


def update_semantic_memory(
    memory: SemanticMemory,
    frame: SemanticFrame,
    intent: IntentEnvelope,
) -> SemanticMemory:
    entities = dict(memory.current_entities)
    if intent.entities.lines:
        entities["line"] = list(intent.entities.lines)
    if intent.entities.stations:
        entities["station"] = list(intent.entities.stations)
    resolved_range = intent.time_scope.get("resolved_range")
    time_range = (
        {"start": str(resolved_range["start"]), "end": str(resolved_range["end"])}
        if isinstance(resolved_range, dict)
        and resolved_range.get("start")
        and resolved_range.get("end")
        else memory.current_time_range
    )
    return SemanticMemory(
        current_entities=entities,
        current_metric=intent.metrics[0] if intent.metrics else memory.current_metric,
        current_time_range=time_range,
        last_operations=list(frame.operations),
        last_route=frame.route,
        updated_at=datetime.now(UTC).isoformat(),
    )


def _entity_candidates(
    data_service: PassengerFlowDataService,
    catalog: dict[str, Any],
    access_context: AccessContext,
    entity_type: str,
) -> list[EntityCandidate]:
    catalog_values = catalog.get("lines" if entity_type == "line" else "stations", [])
    if catalog_values:
        values = [str(value) for value in catalog_values]
        return [
            EntityCandidate(
                id=value,
                name=(
                    f"{index}号线"
                    if entity_type == "line"
                    and data_service.data_scope == "synthetic"
                    and not re.search(r"\d", value)
                    else value
                ),
                type=entity_type,
                confidence=1.0,
                source="registered_catalog",
            )
            for index, value in enumerate(values, start=1)
        ]
    metrics = [item for item in catalog.get("metrics", []) if item.get("id")]
    if not metrics:
        return []
    default_range = catalog.get("default_time_range") or {}
    request = QueryRequest.model_validate(
        {
            "metric": metrics[0]["id"],
            "metric_version": metrics[0].get("version", "1.0.0"),
            "city": catalog.get("city"),
            "dataset_role": "actual",
            "source_version": catalog.get("source_version"),
            "time_grain": "source",
            "time_range": default_range,
            "dimensions": [entity_type],
            "filters": [],
            "limit": min(access_context.row_limit, 1000),
        }
    )
    labels = data_service.entity_labels(entity_type, request, access_context)
    return [
        EntityCandidate(
            id=entity_id,
            name=name,
            type=entity_type,
            confidence=1.0,
            source="observed_database_entity",
        )
        for entity_id, name in sorted(labels.items())
    ]


def _match_candidates(
    raw_text: str, entity_type: str, candidates: list[EntityCandidate]
) -> list[EntityCandidate]:
    target_keys = entity_match_keys(raw_text, entity_type)
    matches: list[EntityCandidate] = []
    for candidate in candidates:
        id_keys = entity_match_keys(candidate.id, entity_type)
        name_keys = entity_match_keys(candidate.name, entity_type)
        candidate_keys = id_keys | name_keys
        exact = _compact(raw_text) in {_compact(candidate.id), _compact(candidate.name)}
        overlap = target_keys & candidate_keys
        contained = any(
            len(left) >= 2 and len(right) >= 2 and (left in right or right in left)
            for left in target_keys
            for right in candidate_keys
        )
        if exact or overlap or contained:
            confidence = 1.0 if exact else 0.98 if overlap else 0.82
            matches.append(candidate.model_copy(update={"confidence": confidence}))
    return sorted(matches, key=lambda item: (-item.confidence, item.id))[:20]


def _task_type(frame: SemanticFrame) -> str:
    operations = set(frame.operations)
    if "help" in operations:
        return "help"
    if frame.route == "general":
        return "general"
    if frame.route == "external" and "travel" not in operations:
        return "external"
    for operation, task_type in (
        ("help", "help"),
        ("travel", "travel"),
        ("forecast", "forecast"),
        ("diagnose", "diagnosis"),
        ("compare", "compare"),
        ("alert", "alert"),
        ("transfer", "transfer"),
        ("geo", "geo"),
        ("correlate", "correlation"),
        ("trend", "trend"),
        ("report", "report"),
    ):
        if operation in operations:
            return task_type
    return "query"


def _fallback_query_operation(question: str) -> str:
    compact = normalize_user_question(question).replace(" ", "")
    if any(token in compact for token in ("所有", "全部", "清单", "有哪些", "给我")):
        return "discover"
    if any(token in compact for token in ("情况", "概况", "介绍", "描述")):
        return "describe"
    if any(token in compact.lower() for token in ("top", "最高", "最低", "前三", "排序")):
        return "rank"
    return "query"


def _fallback_time_text(question: str) -> str | None:
    tokens = ("早高峰", "晚高峰", "昨天", "昨日", "上周", "周末", "工作日")
    return next((token for token in tokens if token in question), None)


def _fallback_target_kind(question: str, intent: IntentEnvelope, operation: str) -> str:
    if intent.entities.lines or any(
        token in normalize_user_question(question) for token in ("号线", "地铁线路", "轨道线路")
    ):
        return "line"
    if intent.entities.stations or any(token in question for token in ("车站", "站点", "地铁站")):
        return "station"
    if operation == "help":
        return "capability"
    if "指标" in question:
        return "metric"
    if any(token in question for token in ("日期", "哪几天", "时间范围")):
        return "date"
    if any(token in question for token in ("数据库", "数据集", "数据概况")):
        return "dataset"
    if operation == "travel":
        return "place"
    if operation == "forecast":
        return "event"
    return "unspecified"


def _compact(value: str) -> str:
    return re.sub(r"[\s，,。！？!?：:（）()\-_]", "", value.lower())
