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
        )
        getattr(packet, _collection_for_kind(kind)).append(item)
        if result.warnings:
            packet.conflicts.extend(result.warnings)
    return packet


def _kind_for_tool(tool: str) -> str:
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
    return {
        "summary": result.summary,
        "rows": result.rows[:20],
        "row_count": len(result.rows),
        "artifact_refs": result.artifact_refs,
    }
