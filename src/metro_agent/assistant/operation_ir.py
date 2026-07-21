from __future__ import annotations

import re
from typing import Any, cast

from metro_agent.assistant.capabilities import CapabilityRegistry
from metro_agent.assistant.schemas import EntityType, IntentEnvelope, OperationIR


class OperationCompiler:
    """Compile validated intent plus user wording into a stable, tool-neutral operation."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self.lexicon = registry.lexicon

    def is_high_confidence(self, question: str, intent: IntentEnvelope) -> bool:
        if intent.needs_clarification or intent.ambiguities:
            return False
        if intent.task_type == "help":
            return True
        if intent.task_type == "general":
            compact = re.sub(r"[\s，,。！？!?：:]", "", question.lower())
            return compact not in {"概览"}
        if self._explicit_operation(question) is not None:
            return True
        return any(
            marker in question.lower() for marker in self.lexicon.get("high_confidence_markers", [])
        )

    def compile(
        self,
        question: str,
        intent: IntentEnvelope,
        *,
        route_confidence: str = "high",
    ) -> OperationIR:
        explicit = self._explicit_operation(question)
        if explicit and explicit[0] in {"list_entities", "describe_entity"}:
            if intent.task_type != "query":
                explicit = None
        operation, entity_type = explicit or (self._operation_for_intent(intent), None)
        if operation == "rank_entities" and entity_type is None:
            entity_type = "station"
        resolved_range = intent.time_scope.get("resolved_range")
        time_range = (
            {"start": str(resolved_range["start"]), "end": str(resolved_range["end"])}
            if isinstance(resolved_range, dict)
            and resolved_range.get("start")
            and resolved_range.get("end")
            else {}
        )
        filters: list[dict[str, Any]] = []
        if intent.entities.lines:
            filters.append({"field": "line_id", "operator": "in", "value": intent.entities.lines})
        if intent.entities.stations:
            filters.append(
                {"field": "station_id", "operator": "in", "value": intent.entities.stations}
            )
        if intent.entities.directions:
            filters.append(
                {"field": "direction", "operator": "in", "value": intent.entities.directions}
            )
        deterministic = operation in {
            "list_entities",
            "describe_entity",
            "list_metrics",
            "list_available_dates",
            "summarize_dataset",
            "capability_readiness",
            "travel_plan",
            "capability_help",
        }
        scope = (
            "external_navigation"
            if operation == "travel_plan"
            else "general_knowledge"
            if operation in {"capability_help", "general_answer"}
            else "approved_observation_window"
            if operation in {"list_entities", "describe_entity"}
            else "registered_catalog"
            if operation in {"list_metrics", "list_available_dates", "summarize_dataset"}
            else "requested_query_scope"
        )
        return OperationIR(
            operation=operation,
            entity_type=entity_type,
            metric=intent.metrics[0] if intent.metrics else None,
            scope=scope,
            time_range=time_range,
            filters=filters,
            completeness_required=True,
            answer_policy="deterministic_summary" if deterministic else "llm_synthesis",
            target_query=(
                self._extract_target_query(question, entity_type)
                if operation == "describe_entity" and entity_type
                else question.strip()
                if operation == "general_answer"
                else None
            ),
            origin=intent.travel_spec.origin if intent.travel_spec else None,
            destination=intent.travel_spec.destination if intent.travel_spec else None,
            travel_mode=intent.travel_spec.mode if intent.travel_spec else None,
            departure_time=intent.travel_spec.departure_time if intent.travel_spec else None,
            route_confidence="model_candidate" if route_confidence == "model_candidate" else "high",
        )

    def _explicit_operation(self, question: str) -> tuple[str, EntityType | None] | None:
        compact = question.lower().replace(" ", "")
        if any(value in compact for value in self.lexicon.get("help_phrases", [])):
            return "capability_help", None
        travel_markers = self.lexicon.get("travel_markers", [])
        if any(marker in compact for marker in travel_markers) and any(
            marker in compact for marker in ("从", "到", "去", "前往")
        ):
            return "travel_plan", None
        if any(value in compact for value in self.lexicon.get("list_metric_phrases", [])):
            return "list_metrics", "metric"
        if any(value in compact for value in self.lexicon.get("list_date_phrases", [])):
            return "list_available_dates", "date"
        if any(value in compact for value in self.lexicon.get("summarize_dataset_phrases", [])):
            return "summarize_dataset", None
        entity_type = self._detect_entity_type(compact)
        if entity_type and any(
            marker in compact for marker in self.lexicon.get("inventory_markers", [])
        ):
            return "list_entities", entity_type
        if entity_type and any(
            marker in compact for marker in self.lexicon.get("describe_markers", [])
        ):
            return "describe_entity", entity_type
        if any(marker in compact for marker in self.lexicon.get("ranking_markers", [])):
            return "rank_entities", entity_type or "station"
        return None

    def _detect_entity_type(self, compact_question: str) -> EntityType | None:
        aliases = self.lexicon.get("entity_aliases", {})
        for entity_type in ("station", "line", "direction", "date", "metric"):
            if any(alias in compact_question for alias in aliases.get(entity_type, [])):
                return cast(EntityType, entity_type)
        return None

    @staticmethod
    def _operation_for_intent(intent: IntentEnvelope) -> str:
        return {
            "query": "query_metric",
            "compare": "compare_periods",
            "forecast": "forecast",
            "alert": "alert",
            "transfer": "transfer",
            "geo": "geo",
            "correlation": "correlation",
            "diagnosis": "diagnosis",
            "trend": "trend_analysis",
            "report": "report",
            "travel": "travel_plan",
            "help": "capability_help",
            "general": "general_answer",
        }[intent.task_type]

    def _extract_target_query(self, question: str, entity_type: EntityType) -> str:
        value = question
        removable = [
            "请",
            "帮我",
            "介绍",
            "描述",
            "一下",
            "基本情况",
            "详细信息",
            "是什么",
            "数据库中的",
            *self.lexicon.get("entity_aliases", {}).get(entity_type, []),
        ]
        for token in removable:
            value = value.replace(token, "")
        return re.sub(r"[，。？！?\s]", "", value).strip()
