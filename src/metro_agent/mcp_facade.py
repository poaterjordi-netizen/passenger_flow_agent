from __future__ import annotations

from typing import Any

from metro_agent.access import AccessContext
from metro_agent.api.models import QueryRequest
from metro_agent.assistant.tool_registry import ToolRegistry

_EXPOSED_TOOLS = {
    "get_metric_catalog",
    "list_metrics",
    "list_available_dates",
    "describe_data_scope",
    "list_observed_entities",
    "describe_observed_entity",
    "resolve_metro_entity",
    "get_data_quality_status",
    "query_metric",
    "execute_query_ir",
    "search_entities",
    "compare_metric_periods",
}


class MetroMcpFacade:
    """Transport-neutral MCP façade over the governed ToolRegistry.

    A deployment adapter may map these methods to MCP JSON-RPC. This class deliberately
    exposes no SQL, table, file-system, shell, write, notification, or action tool.
    """

    def __init__(self, registry: ToolRegistry, access_context: AccessContext | None = None) -> None:
        self.registry = registry
        self.access_context = access_context

    def list_tools(self) -> list[dict[str, Any]]:
        available = _EXPOSED_TOOLS.intersection(self.registry.names)
        if self.registry.data_service.data_scope != "synthetic":
            available.discard("resolve_metro_entity")
        return [self._spec(name) for name in sorted(available)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        available = {item["name"] for item in self.list_tools()}
        if name not in available:
            raise ValueError("MCP tool is not admitted")
        if not isinstance(arguments, dict):
            raise ValueError("MCP tool arguments must be an object")
        result = self.registry.execute("s1", name, arguments, [], self.access_context)
        if result.status != "success":
            raise ValueError(f"MCP tool failed safely: {result.error_code or 'unknown'}")
        return result.model_dump(mode="json")

    @staticmethod
    def _spec(name: str) -> dict[str, Any]:
        if name in {"query_metric", "execute_query_ir", "compare_metric_periods"}:
            schema = QueryRequest.model_json_schema()
        elif name in {"list_observed_entities", "describe_observed_entity", "search_entities"}:
            required = ["entity_type", "query"]
            properties: dict[str, Any] = {
                "entity_type": {"type": "string", "enum": ["station", "line"]},
                "query": QueryRequest.model_json_schema(),
            }
            if name == "describe_observed_entity":
                required.append("target_query")
                properties["target_query"] = {"type": "string", "minLength": 1}
            if name == "search_entities":
                required.append("raw_text")
                properties["raw_text"] = {"type": "string", "minLength": 1}
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": required,
                "properties": properties,
            }
        elif name == "resolve_metro_entity":
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 1}},
            }
        else:
            schema = {"type": "object", "additionalProperties": False}
        return {
            "name": name,
            "description": "Governed metro passenger-flow tool; returns bounded evidence only.",
            "inputSchema": schema,
        }
