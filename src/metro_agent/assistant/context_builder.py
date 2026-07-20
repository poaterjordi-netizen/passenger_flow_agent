from __future__ import annotations

from typing import Any

from metro_agent.api.service import SyntheticApiService


class ContextBuilder:
    """Select bounded business context; never expose SQL or credentials."""

    def __init__(self, data_service: SyntheticApiService, tool_names: list[str]) -> None:
        self.data_service = data_service
        self.tool_names = tool_names

    def build(self, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
        catalog = self.data_service.catalog()
        return {
            "question": question,
            "recent_history": history[-6:],
            "business_dictionary": {
                "早高峰": "07:00-09:00",
                "晚高峰": "17:00-19:00",
                "净流入": "进站量减出站量",
                "换乘": "轨道出站后指定分钟内发生公交上车",
            },
            "catalog": catalog,
            "available_tools": self.tool_names,
            "data_scope": "synthetic",
            "constraints": [
                "only registered metrics and deterministic tools",
                "no free SQL",
                "correlation does not prove causation",
                "forecast is an explainable baseline unless stated otherwise",
            ],
        }
