from __future__ import annotations

import json
import math
import os
import statistics
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.service import SyntheticApiService
from metro_agent.assistant.schemas import ActionPlan, ToolResult

ToolHandler = Callable[[dict[str, Any], list[ToolResult]], dict[str, Any]]


class ToolRegistry:
    """Allowlisted deterministic tools. No free SQL or arbitrary call surface."""

    def __init__(self, data_service: SyntheticApiService, artifact_dir: Path) -> None:
        self.data_service = data_service
        self.artifact_dir = artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolHandler] = {
            "get_metric_catalog": self._catalog,
            "get_audit_summary": self._audit_summary,
            "query_metric": self._query,
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
    ) -> ToolResult:
        handler = self._tools.get(tool)
        if handler is None:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="unknown_tool",
                warnings=["tool is not registered"],
            )
        try:
            output = handler(dict(arguments), dependencies)
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="success",
                summary=output.get("summary", {}),
                rows=output.get("rows", []),
                artifact_refs=output.get("artifact_refs", []),
                warnings=output.get("warnings", []),
            )
        except (ValueError, TypeError, KeyError, statistics.StatisticsError) as exc:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="invalid_tool_input",
                warnings=[str(exc)],
            )
        except Exception:
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="tool_runtime_error",
                warnings=["tool execution failed; implementation details were redacted"],
            )

    def _catalog(self, _: dict[str, Any], __: list[ToolResult]) -> dict[str, Any]:
        catalog = self.data_service.catalog()
        return {"summary": {"claim": "已读取受控指标目录"}, "rows": catalog["metrics"]}

    def _audit_summary(
        self, arguments: dict[str, Any], dependencies: list[ToolResult]
    ) -> dict[str, Any]:
        audit_id = arguments.get("audit_id")
        if audit_id is None and dependencies:
            audit_id = dependencies[-1].summary.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            raise ValueError("audit_id is required directly or from a query dependency")
        audit = self.data_service.audit(audit_id)
        return {
            "summary": {
                "claim": f"审计记录 {audit_id} 已回读，操作类型为 {audit['operation']}",
                "audit_id": audit_id,
            },
            "rows": [audit],
        }

    def _query(self, arguments: dict[str, Any], _: list[ToolResult]) -> dict[str, Any]:
        result = self.data_service.query(QueryRequest.model_validate(arguments))
        total = sum(float(row.get(result["metric"], 0)) for row in result["rows"])
        return {
            "summary": {
                "claim": f"{result['metric']} 查询返回 {result['row_count']} 行，合计 {total:g}",
                "metric": result["metric"],
                "row_count": result["row_count"],
                "total": total,
                "audit_id": result["audit"]["audit_id"],
            },
            "rows": result["rows"],
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
        midpoint = (
            request.time_range.start + (request.time_range.end - request.time_range.start) / 2
        )
        first = request.model_copy(deep=True)
        second = request.model_copy(deep=True)
        first.time_range.end = midpoint
        second.time_range.start = midpoint
        first_result = self.data_service.query(first)
        second_result = self.data_service.query(second)
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
            },
            "rows": [
                {"period": "baseline", "value": first_total},
                {"period": "comparison", "value": second_total},
            ],
            "warnings": ["基期为零，未报告误导性的增长率"] if growth is None else [],
        }

    def _rank(self, arguments: dict[str, Any], dependencies: list[ToolResult]) -> dict[str, Any]:
        rows = _rows(arguments, dependencies)
        metric = arguments.get("metric") or _numeric_column(rows)
        ranked = sorted(rows, key=lambda row: float(row.get(metric, 0)), reverse=True)
        top_n = int(arguments.get("top_n", 10))
        return {
            "summary": {"claim": f"已按 {metric} 识别前 {min(top_n, len(ranked))} 个贡献项"},
            "rows": ranked[:top_n],
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
            result = self.data_service.query(request)
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
            )
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
        dates = self.data_service.catalog()["available_dates"]
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
            "data_scope": "synthetic",
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
            "summary": {"claim": "已生成并保存合成数据分析报告"},
            "rows": [{"report_id": report_id, "data_scope": "synthetic"}],
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


def _rows(arguments: dict[str, Any], dependencies: list[ToolResult]) -> list[dict[str, Any]]:
    if isinstance(arguments.get("rows"), list):
        return arguments["rows"]
    for dependency in dependencies:
        if dependency.rows:
            return dependency.rows
    raise ValueError("tool requires rows from arguments or a dependency")


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
