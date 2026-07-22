from __future__ import annotations

import json
import hashlib
import math
import os
import statistics
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from metro_agent.access import AccessContext, AuthorizationService
from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.service import PassengerFlowDataService
from metro_agent.assistant.schemas import ActionPlan, ToolResult
from metro_agent.assistant.text_normalization import entity_match_keys, line_number

ToolHandler = Callable[[dict[str, Any], list[ToolResult]], dict[str, Any]]

_ACCESS_CONTEXT: ContextVar[AccessContext | None] = ContextVar(
    "metro_tool_access_context", default=None
)

_REQUIRES_COMPLETE_INPUT = {
    "calculate_growth",
    "calculate_correlation",
    "calculate_lagged_correlation",
    "detect_anomalies",
    "decompose_time_series",
    "run_time_series_forecast",
    "backtest_time_series",
    "compare_groups",
    "compare_forecast_with_baseline",
    "diagnose_flow_change",
}


class ToolRegistry:
    """Allowlisted deterministic tools. No free SQL or arbitrary call surface."""

    def __init__(self, data_service: PassengerFlowDataService, artifact_dir: Path) -> None:
        self.data_service = data_service
        self.artifact_dir = artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolHandler] = {
            "get_metric_catalog": self._catalog,
            "list_metrics": self._catalog,
            "list_available_dates": self._available_dates,
            "describe_data_scope": self._data_scope,
            "resolve_metro_entity": self._resolve_entity,
            "search_entities": self._search_entities,
            "describe_observed_entity": self._describe_entity,
            "get_data_quality_status": self._quality_status,
            "get_audit_summary": self._audit_summary,
            "query_metric": self._query,
            "execute_query_ir": self._query,
            "list_observed_entities": self._observed_entities,
            "query_ticket_flow": self._ticket_flow,
            "compare_metric_periods": self._compare,
            "rank_stations": self._rank,
            "calculate_growth": self._growth,
            "calculate_correlation": self._correlation,
            "calculate_lagged_correlation": self._lagged_correlation,
            "get_operational_indicators": self._operational_indicators,
            "detect_anomalies": self._anomalies,
            "decompose_time_series": self._trend,
            "run_time_series_forecast": self._time_series_forecast,
            "backtest_time_series": self._backtest_time_series,
            "compare_groups": self._compare_groups,
            "rank_contributors": self._rank,
            "run_reference_day_forecast": self._reference_forecast,
            "run_station_forecast": self._station_forecast,
            "run_network_forecast": self._network_forecast,
            "find_similar_historical_days": self._similar_days,
            "compare_forecast_with_baseline": self._compare_forecast,
            "run_event_forecast": self._event_forecast,
            "assess_event_forecast_readiness": self._event_forecast_readiness,
            "assess_task_readiness": self._task_readiness,
            "evaluate_forecast": self._evaluate_forecast,
            "query_rail_transactions": self._rail_transactions,
            "query_bus_transactions": self._bus_transactions,
            "match_transfer_records": self._transfer_flow,
            "calculate_transfer_flow": self._transfer_flow,
            "analyze_transfer_window": self._transfer_flow,
            "compare_transfer_rules": self._compare_transfer_rules,
            "geocode_stations": self._geocode,
            "aggregate_flow_by_region": self._geo_aggregate,
            "build_od_heatmap": self._heatmap,
            "build_station_heatmap": self._heatmap,
            "build_commuting_profile": self._commuting_profile,
            "render_geo_dataset": self._heatmap,
            "search_operating_sop": self._sop,
            "search_event_response_cases": self._sop,
            "get_station_capacity_rules": self._capacity,
            "get_alert_thresholds": self._capacity,
            "build_action_candidates": self._sop,
            "diagnose_flow_change": self._diagnosis,
            "build_analysis_report": self._report,
            "build_daily_report": self._report,
            "build_event_report": self._report,
            "build_alert_brief": self._report,
            "export_report": self._report,
            "plan_public_transit_route": self._travel_plan,
            "describe_assistant_capabilities": self._assistant_capabilities,
            "prepare_general_context": self._general_context,
            "prepare_external_context": self._external_context,
        }
        if data_service.data_scope != "synthetic":
            admitted = {
                "get_metric_catalog",
                "list_metrics",
                "list_available_dates",
                "describe_data_scope",
                "get_data_quality_status",
                "get_audit_summary",
                "query_metric",
                "execute_query_ir",
                "search_entities",
                "list_observed_entities",
                "describe_observed_entity",
                "compare_metric_periods",
                "rank_stations",
                "rank_contributors",
                "calculate_growth",
                "assess_event_forecast_readiness",
                "assess_task_readiness",
                "plan_public_transit_route",
                "describe_assistant_capabilities",
                "prepare_general_context",
                "prepare_external_context",
            }
            self._tools = {
                name: handler for name, handler in self._tools.items() if name in admitted
            }

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def execute(
        self,
        step_id: str,
        tool: str,
        arguments: dict[str, Any],
        dependencies: list[ToolResult],
        access_context: AccessContext | None = None,
    ) -> ToolResult:
        handler = self._tools.get(tool)
        if handler is None:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="unknown_tool",
                warnings=["tool is not registered"],
                complete=False,
                block_reason="tool is not registered",
            )
        if tool in _REQUIRES_COMPLETE_INPUT and any(
            not item.complete or item.truncated for item in dependencies
        ):
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="incomplete_dependency",
                warnings=["tool requires complete, non-truncated dependency results"],
                complete=False,
                source_step_ids=[item.step_id for item in dependencies],
                block_reason="incomplete dependency result",
            )
        token = _ACCESS_CONTEXT.set(access_context)
        try:
            output = handler(dict(arguments), dependencies)
            rows = output.get("rows", [])
            summary = output.get("summary", {})
            provenance = summary.get("provenance", {})
            truncated = bool(output.get("truncated", provenance.get("truncated", False)))
            complete = bool(output.get("complete", provenance.get("complete", not truncated)))
            matched = output.get(
                "matched_row_count",
                provenance.get("matched_row_count", provenance.get("total_group_count")),
            )
            coverage = output.get("coverage") or _coverage_for(
                tool=tool,
                arguments=arguments,
                summary=summary,
                rows=rows,
                matched=matched if isinstance(matched, int) else None,
                complete=complete,
                truncated=truncated,
            )
            logical_plan_hash = _hash_payload(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "source_steps": [item.step_id for item in dependencies],
                }
            )
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="success",
                summary=summary,
                rows=rows,
                artifact_refs=output.get("artifact_refs", []),
                warnings=output.get("warnings", []),
                returned_row_count=len(rows),
                matched_row_count=matched if isinstance(matched, int) else None,
                matched_count_unknown=matched is None,
                complete=complete,
                truncated=truncated,
                query_fingerprint=provenance.get("query_fingerprint"),
                logical_plan_hash=logical_plan_hash,
                result_hash=_hash_payload({"summary": summary, "rows": rows}),
                source_step_ids=[item.step_id for item in dependencies],
                calculation_method=output.get("calculation_method") or summary.get("method"),
                policy_snapshot_id=(access_context.policy_snapshot_id if access_context else None),
                access_scope_hash=(access_context.scope_hash() if access_context else None),
                coverage=coverage,
            )
        except PermissionError as exc:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="forbidden",
                warnings=[str(exc)],
                complete=False,
                block_reason="authorization denied",
            )
        except (ValueError, TypeError, KeyError, statistics.StatisticsError) as exc:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="invalid_tool_input",
                warnings=[str(exc)],
                complete=False,
                block_reason=str(exc),
            )
        except Exception:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="tool_runtime_error",
                warnings=["tool execution failed; implementation details were redacted"],
                complete=False,
                block_reason="redacted tool runtime failure",
            )
        finally:
            _ACCESS_CONTEXT.reset(token)

    def _catalog(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        catalog = self.data_service.catalog(_ACCESS_CONTEXT.get())
        metrics = list(catalog["metrics"])
        return {
            "summary": {
                "claim": f"受控指标目录共登记 {len(metrics)} 个可查询指标",
                "provenance": {
                    "city": catalog.get("city"),
                    "source_version": catalog.get("source_version"),
                    "quality_status": catalog.get("quality_status", "unknown"),
                    "data_scope": catalog.get("data_scope"),
                },
            },
            "rows": metrics,
            "complete": True,
            "truncated": False,
            "matched_row_count": len(metrics),
            "coverage": {
                "coverage_type": "registered_catalog",
                "scope_label": "registered_metric_catalog",
                "authoritative_master": True,
                "returned_count": len(metrics),
                "matched_count": len(metrics),
                "complete": True,
                "truncated": False,
                "city": catalog.get("city"),
                "source_version": catalog.get("source_version"),
                "freshness_status": catalog.get("freshness_status"),
            },
        }

    def _available_dates(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        catalog = self.data_service.catalog(_ACCESS_CONTEXT.get())
        rows = [{"date": str(value)} for value in catalog.get("available_dates", [])]
        default_range = catalog.get("default_time_range") or {}
        return {
            "summary": {
                "claim": f"当前准入数据目录覆盖 {len(rows)} 个可用日期",
                "available_date_count": len(rows),
                "time_range": default_range,
                "provenance": {
                    "city": catalog.get("city"),
                    "source_version": catalog.get("source_version"),
                    "data_scope": catalog.get("data_scope"),
                },
            },
            "rows": rows,
            "complete": True,
            "truncated": False,
            "matched_row_count": len(rows),
            "coverage": {
                "coverage_type": "registered_catalog",
                "scope_label": "registered_available_dates",
                "authoritative_master": True,
                "time_range": default_range,
                "returned_count": len(rows),
                "matched_count": len(rows),
                "complete": True,
                "truncated": False,
                "city": catalog.get("city"),
                "dataset_role": "actual",
                "source_version": catalog.get("source_version"),
            },
        }

    def _data_scope(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        catalog = self.data_service.catalog(_ACCESS_CONTEXT.get())
        quality = self.data_service.quality_status(_ACCESS_CONTEXT.get())
        metrics = list(catalog.get("metrics", []))
        dates = list(catalog.get("available_dates", []))
        rows = [
            {
                "data_scope": self.data_service.data_scope,
                "city": catalog.get("city"),
                "source_version": catalog.get("source_version"),
                "dataset_role": "actual",
                "metric_count": len(metrics),
                "available_date_count": len(dates),
                "quality_status": quality.get("status", "unknown"),
                "default_time_start": (catalog.get("default_time_range") or {}).get("start"),
                "default_time_end": (catalog.get("default_time_range") or {}).get("end"),
            }
        ]
        return {
            "summary": {
                "claim": (
                    f"当前为 {self.data_service.data_scope} 数据源，城市 {catalog.get('city')}，"
                    f"登记 {len(metrics)} 个指标、覆盖 {len(dates)} 个可用日期，"
                    f"质量状态为 {quality.get('status', 'unknown')}"
                ),
                "provenance": {
                    "city": catalog.get("city"),
                    "source_version": catalog.get("source_version"),
                    "data_scope": self.data_service.data_scope,
                    "quality_status": quality.get("status", "unknown"),
                },
            },
            "rows": rows,
            "warnings": list(quality.get("flags", [])),
            "complete": True,
            "truncated": False,
            "matched_row_count": 1,
            "coverage": {
                "coverage_type": "registered_catalog",
                "scope_label": "registered_data_product_scope",
                "authoritative_master": True,
                "time_range": catalog.get("default_time_range") or {},
                "returned_count": 1,
                "matched_count": 1,
                "complete": True,
                "truncated": False,
                "city": catalog.get("city"),
                "dataset_role": "actual",
                "source_version": catalog.get("source_version"),
                "freshness_status": quality.get("freshness_status"),
            },
        }

    def _travel_plan(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        origin = str(arguments.get("origin") or "").strip()
        destination = str(arguments.get("destination") or "").strip()
        if not origin or not destination:
            raise ValueError("travel plan requires both origin and destination")
        if _normalize_place(origin) == _normalize_place(destination):
            raise ValueError("travel plan origin and destination must differ")
        mode = str(arguments.get("mode") or "public_transit")
        if mode not in {"public_transit", "driving", "walking"}:
            raise ValueError("unsupported travel mode")
        city = str(arguments.get("city") or "北京").strip() or "北京"
        navigation_links = _navigation_links(origin, destination, city, mode)
        registry = _travel_route_registry()
        matched_route = next(
            (
                route
                for route in registry.get("routes", [])
                if _place_matches(origin, route.get("origin", {}))
                and _place_matches(destination, route.get("destination", {}))
            ),
            None,
        )
        warnings = ["轨道运营状态、临时封站、步行入口和道路情况会变化，出发前请打开实时导航复核。"]
        if matched_route is not None:
            rows = [dict(leg) for leg in matched_route.get("legs", [])]
            route_text = "；".join(
                str(row.get("instruction")).rstrip("。；") for row in rows if row.get("instruction")
            )
            if route_text:
                route_text += "。"
            assumption = str(matched_route.get("assumption") or "").strip()
            claim = f"{assumption}建议路线：{route_text}"
            source_refs = list(matched_route.get("source_refs", []))
            recommendations = [
                "优先采用地铁方案，减少地面交通拥堵的不确定性。",
                "出发前通过实时导航确认首末段步行、出入口和临时运营调整。",
            ]
            route_status = "verified_static_route_with_live_handoff"
            source_version = str(matched_route.get("last_verified") or "") or None
        else:
            rows = [
                {
                    "origin": origin,
                    "destination": destination,
                    "mode": mode,
                    "navigation_url": navigation_links[0]["url"],
                }
            ]
            claim = (
                f"已识别从{origin}到{destination}的出行需求；当前本地路线登记表没有这组地点的"
                "已核验静态线路，已生成实时地图导航入口。"
            )
            source_refs = [
                {
                    "label": "百度地图 URI API 文档",
                    "url": "https://api.map.baidu.com/lbsapi/cloud/uri.htm",
                }
            ]
            recommendations = ["打开实时导航，根据当前交通状态选择公交、驾车或步行方案。"]
            route_status = "live_navigation_handoff"
            source_version = str(registry.get("registry_version") or "") or None
        return {
            "summary": {
                "claim": claim,
                "route_status": route_status,
                "origin": origin,
                "destination": destination,
                "city": city,
                "mode": mode,
                "departure_time": arguments.get("departure_time"),
                "navigation_links": navigation_links,
                "source_refs": source_refs,
                "recommendations": recommendations,
                "assumptions": [
                    str(matched_route.get("assumption"))
                    if matched_route is not None
                    else "起终点按用户输入交给实时地图解析。"
                ],
                "scope": "public_route_reference_and_live_navigation_handoff",
            },
            "rows": rows,
            "warnings": warnings,
            "complete": True,
            "truncated": False,
            "matched_row_count": len(rows),
            "coverage": {
                "coverage_type": "external_navigation",
                "scope_label": "public_route_reference_and_live_navigation_handoff",
                "authoritative_master": False,
                "returned_count": len(rows),
                "matched_count": len(rows),
                "complete": True,
                "truncated": False,
                "city": city,
                "source_version": source_version,
                "freshness_status": "live_handoff_required",
            },
        }

    def _assistant_capabilities(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        registry = _assistant_capability_registry()
        labels = {
            "entity_inventory": "车站与线路清单",
            "metric_catalog": "指标目录",
            "date_catalog": "数据日期范围",
            "data_scope_summary": "数据库概况",
            "entity_description": "实体说明",
            "metric_query": "客流指标查询",
            "entity_ranking": "站点与线路排行",
            "period_comparison": "时段对比",
            "forecast_synthetic": "合成预测演练",
            "forecast_readiness": "真实预测准入检查",
            "synthetic_extended_analysis": "预警、换乘、GIS、诊断、趋势与报告演练",
            "production_capability_readiness": "生产能力准入检查",
            "travel_planning": "出行规划与实时导航",
            "assistant_capability_help": "能力和使用帮助",
            "general_question_answering": "GPT 通用问答",
            "external_information_boundary": "外部实时信息能力边界",
        }
        rows = [
            {
                "capability": str(item.get("id")),
                "label": labels.get(str(item.get("id")), str(item.get("id"))),
                "operations": "、".join(str(value) for value in item.get("operations", [])),
                "answer_policy": str(item.get("answer_policy")),
            }
            for item in registry.get("capabilities", [])
            if self.data_service.data_scope in item.get("data_scopes", [])
        ]
        return {
            "summary": {
                "claim": f"当前智能分析已登记 {len(rows)} 类可路由能力",
                "registry_version": registry.get("registry_version"),
                "scope": "assistant_capability_registry",
            },
            "rows": rows,
            "complete": True,
            "truncated": False,
            "matched_row_count": len(rows),
            "coverage": {
                "coverage_type": "registered_catalog",
                "scope_label": "assistant_capability_registry",
                "authoritative_master": True,
                "returned_count": len(rows),
                "matched_count": len(rows),
                "complete": True,
                "truncated": False,
                "source_version": registry.get("registry_version"),
            },
        }

    def _general_context(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        question = str(arguments.get("question") or "").strip()
        if not question:
            raise ValueError("general answer requires a question")
        rows = [
            {
                "answer_mode": "gpt_general_knowledge",
                "domain_context": "urban_rail_passenger_flow_assistant",
                "data_scope": self.data_service.data_scope,
                "database_rows_included": False,
                "live_external_data_included": False,
            }
        ]
        return {
            "summary": {
                "claim": (
                    "已进入 GPT 通用问答模式；本步骤未读取 metroflow 业务数据行，"
                    "回答不得冒充数据库查询或实时外部事实。"
                ),
                "answer_mode": "gpt_general_knowledge",
                "scope": "general_knowledge_with_explicit_data_boundary",
            },
            "rows": rows,
            "warnings": [
                "通用模型知识可能不是实时信息；涉及当前状态时需要接入并引用外部实时数据源。"
            ],
            "complete": True,
            "truncated": False,
            "matched_row_count": 1,
            "coverage": {
                "coverage_type": "general_context",
                "scope_label": "general_knowledge_with_explicit_data_boundary",
                "authoritative_master": False,
                "returned_count": 1,
                "matched_count": 1,
                "complete": True,
                "truncated": False,
            },
        }

    def _external_context(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        question = str(arguments.get("question") or "").strip()
        if not question:
            raise ValueError("external answer requires a question")
        rows = [
            {
                "answer_mode": "external_live_data_required",
                "database_rows_included": False,
                "external_live_data_included": False,
                "required_tool_classes": ["weather", "events", "live_transit", "web_search"],
            }
        ]
        return {
            "summary": {
                "claim": (
                    "该问题依赖当前外部信息；现有运行时尚未接入对应实时工具，"
                    "因此没有把模型记忆冒充实时事实。"
                ),
                "scope": "external_live_data_capability_boundary",
            },
            "rows": rows,
            "warnings": ["接入并引用实时外部工具后才可给出当前事实结论。"],
            "complete": True,
            "truncated": False,
            "matched_row_count": 1,
            "coverage": {
                "coverage_type": "general_context",
                "scope_label": "external_live_data_capability_boundary",
                "authoritative_master": False,
                "returned_count": 1,
                "matched_count": 1,
                "complete": True,
                "truncated": False,
            },
        }

    def _resolve_entity(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("entity query is required")
        catalog = self.data_service.catalog(_ACCESS_CONTEXT.get())
        candidates = [
            {"entity_type": kind, "id": value, "label": value, "confidence": 1.0}
            for kind, values in (("line", catalog["lines"]), ("station", catalog["stations"]))
            for value in values
            if query.lower() in value.lower()
        ][:20]
        warnings = [] if candidates else ["no authorized entity candidate matched"]
        return {
            "summary": {"claim": f"实体解析返回 {len(candidates)} 个授权候选"},
            "rows": candidates,
            "warnings": warnings,
        }

    def _search_entities(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        raw_text = str(arguments.get("raw_text") or "").strip()
        entity_type = str(arguments.get("entity_type") or "")
        if not raw_text:
            raise ValueError("raw_text is required")
        if entity_type not in {"line", "station"}:
            raise ValueError("entity_type must be line or station")
        inventory = self._observed_entities(arguments, dependencies)
        target_keys = entity_match_keys(raw_text, entity_type)
        name_field = f"{entity_type}_name"
        candidates = []
        requested_line_number = line_number(raw_text) if entity_type == "line" else None
        for index, row in enumerate(inventory["rows"], start=1):
            entity_id = str(row[entity_type])
            entity_name = str(row.get(name_field) or entity_id)
            keys = entity_match_keys(entity_id, entity_type) | entity_match_keys(
                entity_name, entity_type
            )
            exact = raw_text.lower() in {entity_id.lower(), entity_name.lower()}
            overlap = bool(target_keys & keys)
            synthetic_ordinal = (
                self.data_service.data_scope == "synthetic"
                and requested_line_number == index
                and entity_type == "line"
            )
            if exact or overlap or synthetic_ordinal:
                candidates.append(
                    {
                        "id": entity_id,
                        "name": entity_name,
                        "type": entity_type,
                        "confidence": 1.0 if exact else 0.98 if overlap else 0.9,
                        "source": "observed_database_entity",
                    }
                )
        candidates.sort(key=lambda item: (-item["confidence"], item["id"]))
        return {
            "summary": {
                "claim": f"实体原文“{raw_text}”匹配到 {len(candidates)} 个观测候选",
                "raw_text": raw_text,
                "entity_type": entity_type,
                "candidate_count": len(candidates),
                "scope": inventory["summary"]["scope"],
                "provenance": inventory["summary"]["provenance"],
            },
            "rows": candidates[:20],
            "warnings": inventory.get("warnings", []),
            "complete": True,
            "truncated": False,
            "matched_row_count": len(candidates),
            "calculation_method": "deterministic_observed_entity_linking",
            "coverage": {
                **inventory["coverage"],
                "scope_label": "entity_candidates_in_approved_observation_window",
                "returned_count": min(len(candidates), 20),
                "matched_count": len(candidates),
            },
        }

    def _quality_status(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        status = self.data_service.quality_status(_ACCESS_CONTEXT.get())
        return {
            "summary": {
                "claim": f"当前数据质量状态为 {status['status']}",
                "provenance": {
                    "quality_status": status["status"],
                    "source_version": status.get("source_version"),
                    "city": status.get("city"),
                    "data_scope": status.get("data_scope"),
                },
            },
            "rows": [status],
            "warnings": list(status.get("flags", [])),
        }

    def _audit_summary(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        audit_id = arguments.get("audit_id")
        if audit_id is None and dependencies:
            audit_id = dependencies[-1].summary.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            raise ValueError("audit_id is required directly or from a query dependency")
        audit = self.data_service.audit(audit_id, _ACCESS_CONTEXT.get())
        return {
            "summary": {
                "claim": f"审计记录 {audit_id} 已回读，操作类型为 {audit['operation']}",
                "audit_id": audit_id,
            },
            "rows": [audit],
        }

    def _query(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        request = QueryRequest.model_validate(arguments)
        result = self.data_service.query(request, _ACCESS_CONTEXT.get())
        provenance = result.get("provenance", {})
        complete = bool(provenance.get("complete", not provenance.get("truncated", False)))
        total = (
            sum(float(row.get(result["metric"], 0)) for row in result["rows"]) if complete else None
        )
        claim = f"{result['metric']} 查询返回 {result['row_count']} 行"
        if total is not None:
            claim += f"，合计 {total:g}"
        else:
            claim += "；结果不完整，未计算合计"
        return {
            "summary": {
                "claim": claim,
                "metric": result["metric"],
                "row_count": result["row_count"],
                "total": total,
                "audit_id": result["audit"]["audit_id"],
                "query_ir": request.to_query_ir(),
                "provenance": provenance,
            },
            "rows": result["rows"],
            "complete": complete,
            "truncated": bool(provenance.get("truncated", False)),
            "matched_row_count": provenance.get("matched_row_count"),
            "calculation_method": "governed_metric_query",
        }

    def _observed_entities(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        entity_type = str(arguments.get("entity_type") or "")
        if entity_type not in {"station", "line"}:
            raise ValueError("entity_type must be station or line")
        request = QueryRequest.model_validate(arguments.get("query"))
        if request.dimensions != [entity_type]:
            raise ValueError("entity inventory requires exactly one matching dimension")
        if request.order_by:
            raise ValueError("entity inventory must use stable identifier order")

        result = self.data_service.query(request, _ACCESS_CONTEXT.get())
        labels = self.data_service.entity_labels(entity_type, request, _ACCESS_CONTEXT.get())
        provenance = result.get("provenance", {})
        complete = bool(provenance.get("complete", not provenance.get("truncated", False)))
        matched = provenance.get("matched_row_count")
        if not complete or provenance.get("truncated"):
            raise ValueError("entity inventory is incomplete; narrow scope or raise the row limit")

        name_field = f"{entity_type}_name"
        entities: list[dict[str, str]] = []
        seen: set[str] = set()
        for source_row in result.get("rows", []):
            entity_id = source_row.get(entity_type)
            if entity_id is None or not str(entity_id).strip():
                raise ValueError("entity inventory contains a missing identifier")
            normalized_id = str(entity_id).strip()
            if normalized_id in seen:
                raise ValueError("entity inventory contains duplicate identifiers")
            seen.add(normalized_id)
            row = {entity_type: normalized_id}
            entity_name = labels.get(normalized_id)
            if entity_name is not None and str(entity_name).strip():
                row[name_field] = str(entity_name).strip()
            entities.append(row)

        if isinstance(matched, int) and matched != len(entities):
            raise ValueError("entity inventory completeness count does not match returned rows")

        label = "站点" if entity_type == "station" else "线路"
        display_values = [
            (
                f"{row[name_field]}（{row[entity_type]}）"
                if row.get(name_field) and row[name_field] != row[entity_type]
                else row[entity_type]
            )
            for row in entities
        ]
        scope_warning = (
            "该清单是当前已准入实际客流时间窗中完整出现的实体，"
            "不是对数据库全部表进行扫描得到的权威主数据清单"
        )
        warnings = [scope_warning]
        if entities and not any(row.get(name_field) for row in entities):
            warnings.append(f"当前来源没有提供已核验的{label}名称，仅返回编码")
        return {
            "summary": {
                "claim": (
                    f"当前已准入实际客流时间窗中完整观测到 {len(entities)} 个{label}："
                    + "、".join(display_values)
                ),
                "entity_type": entity_type,
                "entity_count": len(entities),
                "entities": entities,
                "scope": "approved_actual_flow_observation_window",
                "authoritative_master": False,
                "scope_warning": scope_warning,
                "query_ir": request.to_query_ir(),
                "provenance": provenance,
            },
            "rows": entities,
            "warnings": warnings,
            "complete": True,
            "truncated": False,
            "matched_row_count": len(entities),
            "calculation_method": "complete_distinct_observed_entity_inventory",
            "coverage": {
                "coverage_type": "observed_window",
                "scope_label": "approved_actual_flow_observation_window",
                "authoritative_master": False,
                "time_range": request.time_range.model_dump(mode="json"),
                "returned_count": len(entities),
                "matched_count": len(entities),
                "complete": True,
                "truncated": False,
                "city": request.city,
                "dataset_role": request.dataset_role,
                "source_version": request.source_version,
                "freshness_status": provenance.get("freshness_status"),
            },
        }

    def _describe_entity(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        inventory = self._observed_entities(arguments, dependencies)
        entity_type = str(arguments.get("entity_type"))
        target = str(arguments.get("target_query") or "").strip().lower()
        if not target:
            raise ValueError("target_query is required")
        name_field = f"{entity_type}_name"
        target_keys = entity_match_keys(target, entity_type)
        matches = []
        for row in inventory["rows"]:
            candidate_keys = entity_match_keys(str(row.get(entity_type, "")), entity_type)
            candidate_keys.update(
                entity_match_keys(str(row.get(name_field, "")), entity_type)
            )
            if target_keys & candidate_keys:
                matches.append(row)
        if not matches:
            raise ValueError("requested entity was not observed in the approved data window")
        label = "站点" if entity_type == "station" else "线路"
        rendered = [
            (
                f"{row.get(name_field)}（{row[entity_type]}）"
                if row.get(name_field) and row.get(name_field) != row[entity_type]
                else str(row[entity_type])
            )
            for row in matches
        ]
        request = QueryRequest.model_validate(arguments.get("query"))
        profile_result = self.data_service.query(request, _ACCESS_CONTEXT.get())
        profile_provenance = profile_result.get("provenance", {})
        if profile_provenance.get("truncated") or not profile_provenance.get("complete", True):
            raise ValueError("entity profile is incomplete; narrow scope or raise the row limit")
        matched_ids = {str(row[entity_type]) for row in matches}
        metric = str(profile_result["metric"])
        metric_label = {
            "entries": "进站量",
            "exits": "出站量",
            "transfers": "换乘量",
            "net_inflow": "净流入",
        }.get(metric, metric)
        metric_rows = [
            row
            for row in profile_result.get("rows", [])
            if str(row.get(entity_type, "")) in matched_ids
        ]
        if len(metric_rows) != len(matches):
            raise ValueError("entity profile does not match the resolved entity set")
        metric_total = sum(float(row[metric]) for row in metric_rows)
        result_rows = []
        values_by_id = {str(row[entity_type]): row[metric] for row in metric_rows}
        for row in matches:
            result_rows.append({**row, metric: values_by_id[str(row[entity_type])]})
        coverage = dict(inventory["coverage"])
        coverage.update(
            {
                "scope_label": "matched_entities_in_approved_observation_window",
                "returned_count": len(matches),
                "matched_count": len(matches),
            }
        )
        return {
            "summary": {
                "claim": f"在当前准入实际客流时间窗中匹配到 {len(matches)} 个{label}："
                + "、".join(rendered)
                + f"；按本次查询指标 {metric_label}（{metric}）汇总为 {metric_total:g}",
                "entity_type": entity_type,
                "target_query": target,
                "metric": metric,
                "metric_total": metric_total,
                "profile_rows": metric_rows,
                "scope": inventory["summary"]["scope"],
                "authoritative_master": False,
                "scope_warning": inventory["summary"]["scope_warning"],
                "query_ir": inventory["summary"]["query_ir"],
                "provenance": inventory["summary"]["provenance"],
            },
            "rows": result_rows,
            "warnings": [
                *inventory["warnings"],
                "用户未明确指标或日期时，实体概况采用当前准入时间窗和默认进站量（entries）指标；可继续指定指标与时间细化查询。",
            ],
            "complete": True,
            "truncated": False,
            "matched_row_count": len(matches),
            "calculation_method": "exact_observed_entity_match",
            "coverage": coverage,
        }

    def _ticket_flow(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        selected = set(str(value) for value in arguments.get("groups", []))
        rows = [
            {"ticket_type": "学生票", "line": "L-A", "hour": "08:00", "passenger_flow": 180},
            {"ticket_type": "学生票", "line": "L-B", "hour": "09:00", "passenger_flow": 145},
            {"ticket_type": "成人票", "line": "L-A", "hour": "17:00", "passenger_flow": 260},
            {"ticket_type": "老年票", "line": "L-B", "hour": "09:00", "passenger_flow": 72},
        ]
        if selected:
            rows = [row for row in rows if row["ticket_type"] in selected]
        return {
            "summary": {"claim": f"按票种、线路和小时返回 {len(rows)} 组合成客流记录"},
            "rows": rows,
            "warnings": ["票种明细为合成演示数据"],
        }

    def _compare(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        request = QueryRequest.model_validate(arguments)
        periods = request.comparison_periods
        if periods is None:
            raise ValueError("comparison requires explicit baseline and comparison periods")
        first = request.model_copy(deep=True)
        second = request.model_copy(deep=True)
        first.time_range = periods.baseline
        second.time_range = periods.comparison
        first.comparison_periods = None
        second.comparison_periods = None
        first.dimensions = []
        second.dimensions = []
        first.order_by = []
        second.order_by = []
        first.limit = 1
        second.limit = 1
        first_result = self.data_service.query(first, _ACCESS_CONTEXT.get())
        second_result = self.data_service.query(second, _ACCESS_CONTEXT.get())
        metric = request.metric
        first_total = sum(float(row.get(metric, 0)) for row in first_result["rows"])
        second_total = sum(float(row.get(metric, 0)) for row in second_result["rows"])
        growth = (
            None
            if first_total == 0 and second_total != 0
            else _growth_rate(first_total, second_total)
        )
        growth_text = "不可计算（基期为零）" if growth is None else f"{growth:.1%}"
        return {
            "summary": {
                "claim": f"前后两个时段 {metric} 从 {first_total:g} 变为 {second_total:g}，变化 {growth_text}",
                "baseline": first_total,
                "comparison": second_total,
                "growth_rate": growth,
                "method": "explicit_period_pair",
                "comparison_relation": periods.relation,
                "provenance": {
                    "complete": True,
                    "truncated": False,
                    "baseline_query_fingerprint": first_result["provenance"].get(
                        "query_fingerprint"
                    ),
                    "comparison_query_fingerprint": second_result["provenance"].get(
                        "query_fingerprint"
                    ),
                },
            },
            "rows": [
                {"period": "baseline", "value": first_total},
                {"period": "comparison", "value": second_total},
            ],
            "warnings": ["基期为零，未报告误导性的增长率"] if growth is None else [],
            "complete": True,
            "matched_row_count": 2,
            "calculation_method": "explicit_period_pair",
        }

    def _rank(self, arguments: dict[str, Any], dependencies: list[ToolResult]) -> dict[str, Any]:
        top_n = int(arguments.get("top_n", 10))
        if not 1 <= top_n <= 100:
            raise ValueError("top_n must be between 1 and 100")
        metric = str(arguments.get("metric") or "")
        query_ir = dependencies[0].summary.get("query_ir") if dependencies else None
        if isinstance(query_ir, dict):
            if not metric:
                metric = str(query_ir.get("metric") or "")
            ranked_request = QueryRequest.model_validate(
                {
                    **query_ir,
                    "order_by": [{"field": metric, "direction": "desc"}],
                    "limit": top_n,
                }
            )
            result = self.data_service.query(ranked_request, _ACCESS_CONTEXT.get())
            rows = result["rows"]
            matched = result.get("provenance", {}).get("matched_row_count")
            return {
                "summary": {
                    "claim": f"已在完整授权范围内按 {metric} 计算全局前 {len(rows)} 项",
                    "metric": metric,
                    "top_n": top_n,
                    "population_row_count": matched,
                    "query_ir": ranked_request.to_query_ir(),
                    "provenance": {
                        **result.get("provenance", {}),
                        "complete": True,
                        "truncated": False,
                        "matched_row_count": matched,
                        "selection": "exact_global_top_n",
                    },
                },
                "rows": rows,
                "complete": True,
                "truncated": False,
                "matched_row_count": matched,
                "calculation_method": "full_scope_group_order_limit",
            }
        if any(not item.complete or item.truncated for item in dependencies):
            raise ValueError("global ranking refuses incomplete or truncated input")
        rows = _rows(arguments, dependencies)
        metric = metric or _numeric_column(rows)
        ranked = sorted(rows, key=lambda row: float(row.get(metric, 0)), reverse=True)
        return {
            "summary": {
                "claim": f"已按完整输入中的 {metric} 识别前 {min(top_n, len(ranked))} 个贡献项"
            },
            "rows": ranked[:top_n],
            "complete": True,
            "matched_row_count": len(ranked),
            "calculation_method": "complete_input_order_limit",
        }

    def _growth(self, arguments: dict[str, Any], dependencies: list[ToolResult]) -> dict[str, Any]:
        baseline = float(arguments.get("baseline", 0))
        comparison = float(arguments.get("comparison", 0))
        if dependencies and (baseline == 0 and comparison == 0):
            values = _numeric_values(dependencies[0].rows)
            if len(values) >= 2:
                baseline, comparison = values[0], values[-1]
        rate = _growth_rate(baseline, comparison)
        return {
            "summary": {"claim": f"指标从 {baseline:g} 变为 {comparison:g}，增长率 {rate:.1%}"},
            "rows": [{"baseline": baseline, "comparison": comparison, "growth_rate": rate}],
        }

    def _correlation(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        x, y = _paired_series(arguments, dependencies)
        coefficient = _pearson(x, y)
        return {
            "summary": {
                "claim": f"同期 Pearson 相关系数为 {coefficient:.3f}；该结果不证明因果",
                "coefficient": coefficient,
                "causal": False,
            },
            "rows": [{"method": "pearson", "coefficient": coefficient, "n": len(x)}],
            "warnings": ["相关性不等于因果关系"],
        }

    def _lagged_correlation(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        x, y = _paired_series(arguments, dependencies)
        if len(x) < 3:
            raise ValueError("lagged correlation requires at least three aligned values")
        coefficient = _pearson(x[:-1], y[1:])
        return {
            "summary": {"claim": f"滞后 1 期相关系数为 {coefficient:.3f}，不证明因果"},
            "rows": [{"lag": 1, "coefficient": coefficient}],
            "warnings": ["滞后相关仍不能单独证明因果"],
        }

    def _anomalies(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        values = [float(value) for value in arguments.get("values", [])]
        if not values and dependencies:
            values = _numeric_values(dependencies[0].rows)
        if not values:
            raise ValueError("values must not be empty")
        threshold = float(arguments.get("threshold", statistics.mean(values) + 2 * _pstdev(values)))
        rows = [
            {"index": index, "value": value, "severity": "high" if value >= threshold else "normal"}
            for index, value in enumerate(values)
            if value >= threshold
        ]
        return {
            "summary": {"claim": f"检测到 {len(rows)} 个超过阈值 {threshold:g} 的异常点"},
            "rows": rows,
        }

    def _trend(self, arguments: dict[str, Any], dependencies: list[ToolResult]) -> dict[str, Any]:
        if dependencies:
            values = _numeric_values(dependencies[0].rows)
        else:
            request = QueryRequest.model_validate({**arguments, "dimensions": ["time"]})
            result = self.data_service.query(request, _ACCESS_CONTEXT.get())
            values = [float(row[request.metric]) for row in result["rows"]]
        if not values:
            raise ValueError("trend requires at least one value")
        slope = (values[-1] - values[0]) / max(len(values) - 1, 1)
        direction = "上升" if slope > 0 else "下降" if slope < 0 else "平稳"
        return {
            "summary": {"claim": f"样例时段趋势为{direction}，每时段平均变化 {slope:g}"},
            "rows": [{"direction": direction, "slope": slope, "points": len(values)}],
        }

    def _time_series_forecast(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        values = [float(value) for value in arguments.get("values", [])]
        if not values and dependencies:
            values = _numeric_values(dependencies[0].rows)
        if len(values) < 2:
            raise ValueError("time-series forecast requires at least two values")
        horizon = int(arguments.get("horizon", 3))
        if not 1 <= horizon <= 24:
            raise ValueError("horizon must be between 1 and 24")
        slope = (values[-1] - values[0]) / (len(values) - 1)
        spread = _pstdev(
            [value - (values[0] + slope * index) for index, value in enumerate(values)]
        )
        rows = []
        for step in range(1, horizon + 1):
            prediction = values[-1] + slope * step
            margin = 1.96 * max(spread, abs(prediction) * 0.05)
            rows.append(
                {
                    "horizon": step,
                    "prediction": prediction,
                    "lower_95": prediction - margin,
                    "upper_95": prediction + margin,
                }
            )
        return {
            "summary": {
                "claim": f"线性基线生成 {horizon} 期趋势预测及 95% 规则区间",
                "method": "linear_extrapolation_baseline",
            },
            "rows": rows,
            "warnings": ["置信区间为合成基线规则区间，未经过生产校准"],
        }

    def _backtest_time_series(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        values = [float(value) for value in arguments.get("values", [])]
        if not values and dependencies:
            values = _numeric_values(dependencies[0].rows)
        if len(values) < 3:
            raise ValueError("time-series backtest requires at least three values")
        errors = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
        mae = statistics.mean(errors)
        return {
            "summary": {
                "claim": f"一步持久性基线回测 MAE 为 {mae:.2f}",
                "method": "rolling_one_step_persistence",
            },
            "rows": [{"mae": mae, "folds": len(errors)}],
        }

    def _compare_groups(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        if len(dependencies) < 2:
            return self._rank(arguments, dependencies)
        metric = str(arguments.get("metric") or "entries")
        labels = [str(value) for value in arguments.get("labels", [])]
        rows = []
        for index, dependency in enumerate(dependencies):
            total = sum(float(row.get(metric, 0)) for row in dependency.rows)
            label = labels[index] if index < len(labels) else dependency.step_id
            rows.append({"group": label, "metric": metric, "value": total})
        return {
            "summary": {"claim": f"已对齐并比较 {len(rows)} 组 {metric} 指标"},
            "rows": rows,
        }

    def _reference_forecast(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        result = self.data_service.forecast(
            ForecastRequest(
                reference_date=arguments["reference_date"],
                target_date=arguments["target_date"],
                scheme_id=int(arguments.get("scheme_id", 1)),
                limit=int(arguments.get("limit", 1000)),
            ),
            _ACCESS_CONTEXT.get(),
        )
        return {
            "summary": {
                "claim": f"参考日复制基线生成 {result['row_count']} 行",
                "method": result["method"],
            },
            "rows": result["rows"],
            "warnings": ["reference_day_copy 不代表机器学习精度"],
        }

    def _station_forecast(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        baseline = self._reference_forecast(arguments, dependencies)
        station = arguments.get("station")
        rows = baseline["rows"]
        if station:
            rows = [row for row in rows if row.get("station_id") == station]
        return {
            "summary": {"claim": f"站点基线预测返回 {len(rows)} 行"},
            "rows": rows,
            "warnings": baseline.get("warnings", []),
        }

    def _network_forecast(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        baseline = self._reference_forecast(arguments, dependencies)
        total = sum(float(row.get("entries", 0)) for row in baseline["rows"])
        return {
            "summary": {"claim": f"线网基线预测进站量合计 {total:g}"},
            "rows": [{"metric": "entries", "network_total": total}],
            "warnings": baseline.get("warnings", []),
        }

    def _similar_days(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        dates = self.data_service.catalog(_ACCESS_CONTEXT.get())["available_dates"]
        return {
            "summary": {"claim": f"合成数据中找到 {len(dates)} 个可用历史活动参考日"},
            "rows": [
                {
                    "date": str(value),
                    "event_type": "synthetic_large_event",
                    "attendance": 20_000,
                    "similarity": 1.0,
                }
                for value in dates
            ],
            "warnings": ["相似活动记录为合成架构验证样例"],
        }

    def _compare_forecast(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        baseline = arguments.get("baseline")
        forecast = arguments.get("forecast")
        if len(dependencies) >= 2:
            baseline = sum(float(row.get("entries", 0)) for row in dependencies[0].rows)
            forecast = sum(float(row.get("entries", 0)) for row in dependencies[1].rows)
        elif baseline is None or forecast is None:
            rows = _rows(arguments, dependencies)
            baseline = sum(float(row.get("entries", 0)) for row in rows)
            forecast = baseline
        baseline = float(baseline)
        forecast = float(forecast)
        return self._growth({"baseline": baseline, "comparison": forecast}, [])

    def _operational_indicators(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        rows = [
            {"time": "08:00", "on_time_rate": 0.98, "equipment_failures": 1},
            {"time": "09:00", "on_time_rate": 0.96, "equipment_failures": 2},
            {"time": "17:00", "on_time_rate": 0.94, "equipment_failures": 3},
            {"time": "18:00", "on_time_rate": 0.91, "equipment_failures": 5},
        ]
        return {
            "summary": {"claim": "读取 4 个时段的模拟正点率与设备故障指标"},
            "rows": rows,
            "warnings": ["运营指标为合成演示数据"],
        }

    def _event_forecast(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        attendance = int(arguments.get("attendance", 20_000))
        if attendance < 0 or attendance > 200_000:
            raise ValueError("attendance must be between 0 and 200000")
        if dependencies and dependencies[0].rows:
            baseline = {"rows": dependencies[0].rows}
        else:
            baseline = self._reference_forecast(
                {
                    "reference_date": arguments["reference_date"],
                    "target_date": arguments["target_date"],
                    "scheme_id": 1,
                },
                [],
            )
        factor = 1 + min(attendance / 100_000, 1.5)
        impacted_stations = set(str(value) for value in arguments.get("impacted_stations", []))
        rows = []
        for row in baseline["rows"]:
            value = dict(row)
            if not impacted_stations or value.get("station_id") in impacted_stations:
                for metric in ("entries", "exits", "transfers"):
                    value[metric] = round(float(value[metric]) * factor)
            rows.append(value)
        baseline_total = sum(
            float(row["entries"])
            for row in baseline["rows"]
            if not impacted_stations or row.get("station_id") in impacted_stations
        )
        event_total = sum(
            float(row["entries"])
            for row in rows
            if not impacted_stations or row.get("station_id") in impacted_stations
        )
        return {
            "summary": {
                "claim": f"{attendance} 人活动规则情景使受影响站点进站基线从 {baseline_total:g} 增至 {event_total:g}",
                "method": "reference_day_copy_plus_attendance_factor",
                "factor": factor,
                "impacted_stations": sorted(impacted_stations),
            },
            "rows": rows,
            "warnings": ["活动修正系数为架构验证规则，尚未经过真实活动回测"],
        }

    def _event_forecast_readiness(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        attendance = int(arguments.get("attendance", 0))
        if not 0 <= attendance <= 200_000:
            raise ValueError("attendance must be between 0 and 200000")
        venue = str(arguments.get("venue") or "未提供场馆")
        target_date = str(arguments.get("target_date") or "未提供活动日期")
        actual_context_available = bool(
            dependencies
            and dependencies[0].status == "success"
            and dependencies[0].complete
            and not dependencies[0].truncated
        )
        requirements = [
            ("event_time", "补充活动日期、开演时间、散场时间和预测时间窗"),
            ("venue_station_mapping", f"由业务负责人核验 {venue} 到真实车站编码的映射"),
            ("similar_event_actuals", "提供相似活动客流实绩、实际到场人数和进散场曲线"),
            ("approved_forecast_model", "登记并审批预测模型版本、回测指标和不确定性口径"),
            ("approved_operating_sop", "接入经审批的一站一方案、运力和容量约束后再给出处置建议"),
        ]
        return {
            "summary": {
                "claim": (
                    f"已收到 {venue}、{attendance} 人的活动预测请求；当前仅有完整实际客流上下文，"
                    "活动预测数据产品和模型尚未准入，因此未生成数值预测或运营处置方案"
                ),
                "method": "forecast_admission_readiness_check",
                "forecast_status": "not_admitted",
                "requested_target_date": target_date,
                "actual_context_available": actual_context_available,
                "numeric_forecast_generated": False,
                "provenance": {
                    "dataset_role": "actual",
                    "forecast_status": "not_admitted",
                    "quality_status": "warning",
                },
            },
            "rows": [
                {
                    "requirement": requirement,
                    "status": "missing_or_unverified",
                    "action": action,
                }
                for requirement, action in requirements
            ],
            "warnings": [
                "可用实际客流窗口不是该活动的预测基线",
                "没有使用合成活动系数、未核验预测表或模型猜测生成数值",
                "所有运营建议仍需业务负责人确认",
            ],
            "complete": True,
            "matched_row_count": len(requirements),
            "calculation_method": "forecast_admission_readiness_check",
        }

    def _task_readiness(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        task_type = str(arguments.get("task_type") or "unknown")
        requirements_by_task = {
            "alert": ["实时密度权威源", "经审批阈值", "值班处置 SOP"],
            "correlation": ["同期运营指标", "时间对齐规则", "统计分析验收"],
            "diagnosis": ["行车与设备事件", "日历和活动数据", "原因证据判定规则"],
            "geo": ["经核验站点坐标", "OD 权威源", "地图数据使用审批"],
            "report": ["报告模板", "导出权限", "审批和留存策略"],
            "transfer": ["轨道交易明细", "公交交易明细", "隐私审批和匹配规则"],
            "trend": ["足够长的连续历史窗口", "趋势模型回测", "模型版本登记"],
        }
        requirements = requirements_by_task.get(
            task_type,
            ["该任务对应的权威数据产品", "确定性计算工具", "业务验收规则"],
        )
        return {
            "summary": {
                "claim": (
                    f"当前真实数据产品未准入 {task_type} 任务所需的全部证据；"
                    "本次未执行合成计算，也未生成运营结论"
                ),
                "method": "capability_admission_readiness_check",
                "task_status": "not_admitted",
                "provenance": {"quality_status": "warning"},
            },
            "rows": [
                {
                    "requirement": requirement,
                    "status": "missing_or_unverified",
                    "action": f"接入并审批：{requirement}",
                }
                for requirement in requirements
            ],
            "warnings": ["能力准入检查不是业务分析结论"],
            "complete": True,
            "matched_row_count": len(requirements),
            "calculation_method": "capability_admission_readiness_check",
        }

    def _evaluate_forecast(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        actual = [float(value) for value in arguments.get("actual", [100, 120, 140])]
        predicted = [float(value) for value in arguments.get("predicted", [105, 118, 150])]
        if len(actual) != len(predicted) or not actual:
            raise ValueError("actual and predicted must be non-empty and aligned")
        mae = statistics.mean(abs(a - p) for a, p in zip(actual, predicted, strict=True))
        return {"summary": {"claim": f"样例回测 MAE 为 {mae:.2f}"}, "rows": [{"mae": mae}]}

    def _rail_transactions(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        return {"summary": {"claim": "读取 4 条模拟轨道出站记录"}, "rows": _rail_rows()}

    def _bus_transactions(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        return {"summary": {"claim": "读取 4 条模拟公交上车记录"}, "rows": _bus_rows()}

    def _transfer_flow(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        window = int(arguments.get("window_minutes", 30))
        if not 5 <= window <= 120:
            raise ValueError("window_minutes must be between 5 and 120")
        rail_rows = _rail_rows()
        bus_rows = _bus_rows()
        if len(dependencies) >= 2:
            rail_rows = dependencies[0].rows
            bus_rows = dependencies[1].rows
        elif len(dependencies) == 1 and dependencies[0].rows:
            if "transfer_count" in dependencies[0].rows[0]:
                count = sum(int(row["transfer_count"]) for row in dependencies[0].rows)
                return {
                    "summary": {"claim": f"按 {window} 分钟规则汇总到 {count} 次模拟换乘"},
                    "rows": dependencies[0].rows,
                }
        bus_by_person = {row["person_id"]: row for row in bus_rows}
        station_counts: dict[str, int] = {}
        for rail in rail_rows:
            bus = bus_by_person.get(rail["person_id"])
            if bus and 0 <= bus["minute"] - rail["minute"] <= window:
                station_counts[rail["station"]] = station_counts.get(rail["station"], 0) + 1
        rows = [
            {"station": station, "transfer_count": count}
            for station, count in sorted(station_counts.items())
        ]
        return {
            "summary": {
                "claim": f"按 {window} 分钟规则匹配到 {sum(station_counts.values())} 次模拟换乘"
            },
            "rows": rows,
        }

    def _compare_transfer_rules(
        self, arguments: dict[str, Any], _: list[ToolResult]
    ) -> dict[str, Any]:
        first = int(arguments.get("first_window", 30))
        second = int(arguments.get("second_window", 45))
        a = self._transfer_flow({"window_minutes": first}, [])
        b = self._transfer_flow({"window_minutes": second}, [])
        return {
            "summary": {"claim": f"阈值从 {first} 调至 {second} 分钟，匹配量变化已复算"},
            "rows": [
                {"window": first, "count": sum(row["transfer_count"] for row in a["rows"])},
                {"window": second, "count": sum(row["transfer_count"] for row in b["rows"])},
            ],
        }

    def _geocode(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        return {"summary": {"claim": "已映射 2 个模拟车站坐标"}, "rows": _station_coordinates()}

    def _geo_aggregate(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        rows = [
            {**item, "region": "核心区", "flow": 375 if item["station"] == "S-ALPHA" else 125}
            for item in _station_coordinates()
        ]
        return {"summary": {"claim": "已按模拟核心区聚合站点客流"}, "rows": rows}

    def _heatmap(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        coordinates = {item["station"]: item for item in _station_coordinates()}
        rows = [
            {"origin": "S-ALPHA", "destination": "S-BETA", "flow": 180},
            {"origin": "S-BETA", "destination": "S-ALPHA", "flow": 95},
        ]
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "origin": row["origin"],
                        "destination": row["destination"],
                        "flow": row["flow"],
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [
                                coordinates[row["origin"]]["longitude"],
                                coordinates[row["origin"]]["latitude"],
                            ],
                            [
                                coordinates[row["destination"]]["longitude"],
                                coordinates[row["destination"]]["latitude"],
                            ],
                        ],
                    },
                }
                for row in rows
            ],
        }
        artifact = self._write_artifact(
            "od-heatmap", {"data_scope": "synthetic", "heat_rows": rows, "geojson": geojson}
        )
        return {
            "summary": {"claim": "生成 2 条模拟 OD 热力数据"},
            "rows": rows,
            "artifact_refs": [str(artifact)],
            "warnings": ["坐标和 OD 均为合成演示数据"],
        }

    def _commuting_profile(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        return {
            "summary": {"claim": "模拟通勤主方向为 S-ALPHA 至 S-BETA"},
            "rows": [{"origin": "S-ALPHA", "destination": "S-BETA", "share": 0.65}],
        }

    def _sop(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        scenario = str(arguments.get("scenario", "crowding"))
        actions = {
            "large_event": ["提前布置客流隔离设施", "按预测峰值设置弹性进站闸门", "安排人工复核"],
            "crowding": ["现场确认站台密度", "准备限流但不得自动执行", "通知值班负责人确认"],
        }.get(scenario, ["由值班负责人复核后处置"])
        action_plan = ActionPlan(
            severity="critical" if scenario == "crowding" else "warning",
            actions=actions,
            notification_candidates=["值班负责人"],
            requires_human_confirmation=True,
        )
        return {
            "summary": {
                "claim": f"召回 {scenario} 场景的 {len(actions)} 条模拟 SOP 建议",
                "action_plan": action_plan.model_dump(mode="json"),
                "rationale": [f"synthetic {scenario} evidence"],
            },
            "rows": [
                {
                    "priority": index + 1,
                    "action": action,
                    "notification_candidate": action_plan.notification_candidates[0],
                    "requires_confirmation": True,
                }
                for index, action in enumerate(action_plan.actions)
            ],
        }

    def _capacity(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        return {
            "summary": {"claim": "模拟站台密度预警阈值为 0.80"},
            "rows": [{"metric": "platform_density", "warning": 0.8, "critical": 0.9}],
        }

    def _diagnosis(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        query_total = None
        if dependencies and dependencies[0].rows:
            metric = str(arguments.get("metric", "entries"))
            query_total = sum(float(row.get(metric, 0)) for row in dependencies[0].rows)
        if query_total is None:
            query_total = self._query(arguments, [])["summary"]["total"]
        hypotheses = [
            {"candidate": "星期与节假日结构", "status": "missing_evidence"},
            {"candidate": "行车或设备异常", "status": "missing_evidence"},
            {"candidate": "数据质量异常", "status": "not_observed_in_contract_validation"},
            {"candidate": "客流发生变化", "status": "supported", "value": query_total},
        ]
        return {
            "summary": {"claim": "已建立原因候选树；仅客流数据本身有证据，其余原因需补充数据"},
            "rows": hypotheses,
            "warnings": ["候选原因不等于因果结论"],
        }

    def _report(self, arguments: dict[str, Any], dependencies: list[ToolResult]) -> dict[str, Any]:
        context = _ACCESS_CONTEXT.get()
        if context is None:
            context = AccessContext.synthetic_local()
        AuthorizationService.authorize_export(context)
        if dependencies:
            source = dependencies
        else:
            source = [
                ToolResult(
                    step_id="source",
                    tool="query_metric",
                    status="success",
                    **self._query(arguments, []),
                )
            ]
        report_id = f"report-{uuid.uuid4().hex}"
        target = self.artifact_dir / f"{report_id}.json"
        payload = {
            "report_id": report_id,
            "generated_at": datetime.now().astimezone().isoformat(),
            "data_scope": self.data_service.data_scope,
            "sections": [result.model_dump(mode="json") for result in source],
        }
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "summary": {
                "claim": "已生成并保存受控数据分析报告",
                "provenance": {"data_scope": self.data_service.data_scope},
            },
            "rows": [{"report_id": report_id, "data_scope": self.data_service.data_scope}],
            "artifact_refs": [str(target)],
        }

    def _write_artifact(self, prefix: str, payload: dict[str, Any]) -> Path:
        target = self.artifact_dir / f"{prefix}-{uuid.uuid4().hex}.json"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def _assistant_capability_registry() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "assistant_capabilities.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("capabilities"), list):
        raise ValueError("assistant capability registry is invalid")
    return payload


def _travel_route_registry() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "travel_routes.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("routes"), list):
        raise ValueError("travel route registry is invalid")
    return payload


def _normalize_place(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _place_matches(value: str, registered: dict[str, Any]) -> bool:
    normalized = _normalize_place(value)
    aliases = [registered.get("name"), *registered.get("aliases", [])]
    candidates = [_normalize_place(str(alias)) for alias in aliases if alias]
    return any(
        normalized == candidate
        or (len(normalized) >= 3 and normalized in candidate)
        or (len(candidate) >= 3 and candidate in normalized)
        for candidate in candidates
    )


def _navigation_links(
    origin: str, destination: str, city: str, requested_mode: str
) -> list[dict[str, str]]:
    modes = [requested_mode]
    if requested_mode == "public_transit":
        modes.append("driving")
    api_modes = {
        "public_transit": ("transit", "百度地图实时公交导航"),
        "driving": ("driving", "百度地图实时驾车导航"),
        "walking": ("walking", "百度地图实时步行导航"),
    }
    links = []
    for mode in modes:
        api_mode, label = api_modes[mode]
        query = urlencode(
            {
                "origin": origin,
                "destination": destination,
                "mode": api_mode,
                "region": city,
                "output": "html",
                "src": "metro-passenger-flow-agent",
            }
        )
        links.append({"label": label, "url": f"https://api.map.baidu.com/direction?{query}"})
    return links


def _rows(arguments: dict[str, Any], dependencies: list[ToolResult]) -> list[dict[str, Any]]:
    if isinstance(arguments.get("rows"), list):
        return arguments["rows"]
    for dependency in dependencies:
        if dependency.rows:
            return dependency.rows
    raise ValueError("tool requires rows from arguments or a dependency")


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _coverage_for(
    *,
    tool: str,
    arguments: dict[str, Any],
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    matched: int | None,
    complete: bool,
    truncated: bool,
) -> dict[str, Any]:
    """Normalize every deterministic result into a machine-checkable coverage claim."""

    provenance = summary.get("provenance") or {}
    query_ir = summary.get("query_ir") or arguments.get("query") or arguments
    time_range = query_ir.get("time_range", {}) if isinstance(query_ir, dict) else {}
    derived = any(
        marker in tool
        for marker in (
            "calculate_",
            "compare_",
            "rank_",
            "detect_",
            "decompose_",
            "forecast",
            "diagnose_",
            "build_",
        )
    )
    readiness = tool.startswith("assess_")
    role = provenance.get("dataset_role")
    if role not in {"actual", "reference", "forecast"}:
        role = query_ir.get("dataset_role") if isinstance(query_ir, dict) else None
    if role not in {"actual", "reference", "forecast"}:
        role = None
    return {
        "coverage_type": (
            "capability_readiness" if readiness else "derived_result" if derived else "query_result"
        ),
        "scope_label": str(summary.get("scope") or "requested_query_scope"),
        "authoritative_master": bool(summary.get("authoritative_master", False)),
        "time_range": time_range if isinstance(time_range, dict) else {},
        "returned_count": len(rows),
        "matched_count": matched,
        "complete": complete,
        "truncated": truncated,
        "city": provenance.get("city")
        or (query_ir.get("city") if isinstance(query_ir, dict) else None),
        "dataset_role": role,
        "source_version": provenance.get("source_version")
        or (query_ir.get("source_version") if isinstance(query_ir, dict) else None),
        "freshness_status": provenance.get("freshness_status"),
    }


def _numeric_column(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return key
    raise ValueError("rows contain no numeric column")


def _numeric_values(rows: list[dict[str, Any]]) -> list[float]:
    column = _numeric_column(rows)
    return [float(row[column]) for row in rows]


def _paired_series(
    arguments: dict[str, Any], dependencies: list[ToolResult]
) -> tuple[list[float], list[float]]:
    if "x" in arguments or "y" in arguments:
        return (
            [float(value) for value in arguments.get("x", [])],
            [float(value) for value in arguments.get("y", [])],
        )
    if len(dependencies) >= 2:
        first = _numeric_values(dependencies[0].rows)
        second_rows = dependencies[1].rows
        preferred = "on_time_rate" if second_rows and "on_time_rate" in second_rows[0] else None
        second = (
            [float(row[preferred]) for row in second_rows]
            if preferred
            else _numeric_values(second_rows)
        )
        length = min(len(first), len(second))
        return first[:length], second[:length]
    return [500, 540, 490, 610, 580, 640], [0.97, 0.96, 0.98, 0.94, 0.95, 0.93]


def _growth_rate(baseline: float, comparison: float) -> float:
    if baseline == 0:
        if comparison == 0:
            return 0.0
        raise ValueError("growth rate is undefined for a zero baseline")
    return (comparison - baseline) / baseline


def _pearson(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("correlation inputs must be aligned and contain at least two values")
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y))
    if denominator == 0:
        raise ValueError("correlation is undefined for a constant series")
    return numerator / denominator


def _pstdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _rail_rows() -> list[dict[str, Any]]:
    return [
        {"person_id": "P1", "station": "S-ALPHA", "minute": 0},
        {"person_id": "P2", "station": "S-ALPHA", "minute": 5},
        {"person_id": "P3", "station": "S-BETA", "minute": 10},
        {"person_id": "P4", "station": "S-BETA", "minute": 20},
    ]


def _bus_rows() -> list[dict[str, Any]]:
    return [
        {"person_id": "P1", "stop": "B-1", "minute": 20},
        {"person_id": "P2", "stop": "B-1", "minute": 48},
        {"person_id": "P3", "stop": "B-2", "minute": 35},
        {"person_id": "P4", "stop": "B-2", "minute": 100},
    ]


def _station_coordinates() -> list[dict[str, Any]]:
    return [
        {"station": "S-ALPHA", "longitude": 116.397, "latitude": 39.908},
        {"station": "S-BETA", "longitude": 116.407, "latitude": 39.918},
    ]
