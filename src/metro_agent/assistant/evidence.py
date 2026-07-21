from __future__ import annotations

from typing import Any

from metro_agent.assistant.schemas import EvidenceItem, EvidencePacket, ToolResult


def build_evidence_packet(question: str, results: list[ToolResult]) -> EvidencePacket:
    packet = EvidencePacket(question=question)
    for result in results:
        if result.status != "success":
            packet.missing_evidence.append(f"{result.step_id}:{result.tool} 未成功")
            continue
        kind = _kind_for_tool(result.tool)
        claim = str(result.summary.get("claim") or result.summary.get("description") or result.tool)
        item = EvidenceItem(
            evidence_id=f"ev-{result.step_id}",
            step_id=result.step_id,
            kind=kind,
            claim=claim,
            value=_bounded_value(result),
            metadata=dict(result.summary.get("provenance") or {}),
            structured_claims=_structured_claims(result),
            result_schema=_result_schema(result.rows),
            returned_row_count=result.returned_row_count,
            matched_row_count=result.matched_row_count,
            matched_count_unknown=result.matched_count_unknown,
            complete=result.complete,
            truncated=result.truncated,
            query_fingerprint=result.query_fingerprint,
            logical_plan_hash=result.logical_plan_hash,
            result_hash=result.result_hash,
            source_evidence_ids=[f"ev-{step_id}" for step_id in result.source_step_ids],
            calculation_method=result.calculation_method,
            policy_snapshot_id=result.policy_snapshot_id,
            access_scope_hash=result.access_scope_hash,
            warnings=result.warnings,
            block_reason=result.block_reason,
            coverage=result.coverage,
        )
        getattr(packet, _collection_for_kind(kind)).append(item)
        if result.warnings:
            packet.conflicts.extend(result.warnings)
    return packet


def _kind_for_tool(tool: str) -> str:
    if tool in {"prepare_general_context", "describe_assistant_capabilities"}:
        return "knowledge"
    if tool.endswith("readiness"):
        return "knowledge"
    if "sop" in tool or "capacity" in tool or "threshold" in tool:
        return "knowledge"
    if "forecast" in tool:
        return "model_output"
    if "heatmap" in tool or "geo" in tool:
        return "chart"
    if any(
        token in tool for token in ("correlation", "growth", "anomal", "trend", "decompose", "rank")
    ):
        return "statistic"
    return "fact"


def _collection_for_kind(kind: str) -> str:
    return {
        "fact": "facts",
        "statistic": "statistics",
        "chart": "charts",
        "model_output": "model_outputs",
        "knowledge": "knowledge_sources",
    }[kind]


def _bounded_value(result: ToolResult) -> dict[str, Any]:
    discovery_tools = {
        "list_observed_entities",
        "describe_observed_entity",
        "list_metrics",
        "list_available_dates",
        "describe_data_scope",
        "describe_assistant_capabilities",
    }
    row_limit = len(result.rows) if result.tool in discovery_tools else 20
    return {
        "summary": result.summary,
        "rows": result.rows[:row_limit],
        "returned_row_count": result.returned_row_count,
        "matched_row_count": result.matched_row_count,
        "complete": result.complete,
        "truncated": result.truncated,
        "evidence_value_truncated": len(result.rows) > row_limit,
        "artifact_refs": result.artifact_refs,
        "provenance": result.summary.get("provenance", {}),
        "coverage": result.coverage.model_dump(mode="json"),
    }


def _structured_claims(result: ToolResult) -> list[dict[str, Any]]:
    metric = result.summary.get("metric")
    claims: list[dict[str, Any]] = []
    if metric and result.summary.get("total") is not None:
        provenance = result.summary.get("provenance", {})
        claims.append(
            {
                "claim_type": "metric_total",
                "metric_id": metric,
                "metric_version": provenance.get("metric_version"),
                "unit": provenance.get("metric_unit"),
                "value": result.summary["total"],
                "aggregation": "sum",
            }
        )
    for row in result.rows[:20]:
        numeric = {
            key: value
            for key, value in row.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if numeric:
            claims.append(
                {
                    "claim_type": "result_row",
                    "dimensions": {key: value for key, value in row.items() if key not in numeric},
                    "values": numeric,
                }
            )
    return claims


def _result_schema(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    fields: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            fields.setdefault(key, _type_name(value))
    return [{"field": key, "type": fields[key]} for key in sorted(fields)]


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return "string"
