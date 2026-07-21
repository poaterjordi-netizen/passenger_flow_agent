from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metro_agent.assistant.schemas import (
    CapabilityDefinition,
    CapabilityMatch,
    OperationIR,
)

DEFAULT_CAPABILITY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "assistant_capabilities.json"
)


class CapabilityRegistry:
    """Validated, declarative mapping from OperationIR to admitted deterministic tools."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or DEFAULT_CAPABILITY_PATH).resolve()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError("assistant capability registry schema_version is unsupported")
        self.registry_version = str(payload.get("registry_version") or "")
        if not self.registry_version:
            raise ValueError("assistant capability registry version is required")
        lexicon = payload.get("lexicon")
        if not isinstance(lexicon, dict):
            raise ValueError("assistant capability lexicon must be an object")
        self.lexicon: dict[str, Any] = lexicon
        raw_capabilities = payload.get("capabilities")
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            raise ValueError("assistant capability registry must contain capabilities")
        self.definitions = [CapabilityDefinition.model_validate(item) for item in raw_capabilities]
        ids = [item.id for item in self.definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("assistant capability registry contains duplicate ids")

    def match(
        self,
        operation: OperationIR,
        *,
        data_scope: str,
        available_tools: set[str],
    ) -> CapabilityMatch:
        candidates = [
            item
            for item in self.definitions
            if operation.operation in item.operations and data_scope in item.data_scopes
        ]
        if operation.entity_type is not None:
            typed = [
                item
                for item in candidates
                if not item.entity_types or operation.entity_type in item.entity_types
            ]
            candidates = typed
        for definition in candidates:
            missing_slots = [
                slot for slot in definition.required_slots if not _slot_present(operation, slot)
            ]
            unavailable_tools = sorted(set(definition.tools) - available_tools)
            available_for_capability = sorted(set(definition.tools) & available_tools)
            if not missing_slots and available_for_capability:
                return CapabilityMatch(
                    status="matched",
                    capability_id=definition.id,
                    registry_version=self.registry_version,
                    tools=definition.tools,
                    answer_policy=definition.answer_policy,
                    completeness_policy=definition.completeness_policy,
                    unavailable_tools=unavailable_tools,
                )
            if missing_slots:
                return CapabilityMatch(
                    status="missing_slots",
                    capability_id=definition.id,
                    registry_version=self.registry_version,
                    tools=definition.tools,
                    answer_policy=definition.answer_policy,
                    completeness_policy=definition.completeness_policy,
                    missing_slots=missing_slots,
                    unavailable_tools=unavailable_tools,
                )
        return CapabilityMatch(
            status="unavailable",
            registry_version=self.registry_version,
            answer_policy="deterministic_summary",
            unavailable_tools=sorted(
                {tool for item in candidates for tool in item.tools} - available_tools
            ),
        )

    def public_definitions(self, data_scope: str, available_tools: set[str]) -> list[dict[str, Any]]:
        return [
            {
                **item.model_dump(mode="json"),
                "runtime_tools_available": sorted(set(item.tools) & available_tools),
                "runtime_tools_unavailable": sorted(set(item.tools) - available_tools),
            }
            for item in self.definitions
            if data_scope in item.data_scopes
        ]


def _slot_present(operation: OperationIR, slot: str) -> bool:
    if slot == "time_range":
        return bool(operation.time_range.get("start") and operation.time_range.get("end"))
    value = getattr(operation, slot, None)
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return value is not None
