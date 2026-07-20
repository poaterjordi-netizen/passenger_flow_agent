#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "assistant_gold_cases.json"

QUERY_CASES = [
    "查询各站进站客流",
    "查询各站出站客流并排序",
    "查询 1 号线各站换乘客流",
    "查询 2 号线上行净流入",
    "查询 S-ALPHA 站进站量",
    "查询各线路进站客流",
    "查询各方向出站客流",
    "查询各站进站客流，只看前三名",
    "按小时列出进站客流明细",
    "查询晚高峰各站净流入并排序",
]
COMPARE_CASES = [
    "比较 1 号线和 2 号线工作日晚高峰进站客流",
    "对比 1 号线和 2 号线各站出站客流",
    "比较 1 号线和 2 号线换乘客流",
    "比较 1 号线和 2 号线上行净流入",
    "对比 1 号线与 2 号线客流并结合设备故障次数分析",
    "比较两个时段进站客流",
    "环比两个时段出站客流",
    "同比两个时段换乘客流",
    "比较两个时段净流入",
    "对比早晚两个时段进站客流",
]
ALERT_CASES = [
    "实时站台密度预警",
    "摄像头显示站台密度 0.82，请做预警研判",
    "列车满载率 0.95，生成实时预警",
    "进站速率持续上升，请给出预警建议",
    "实时拥挤异常研判并列出待确认操作",
    "站台密度超过阈值时生成预警卡片",
    "摄像头客流突然升高，检索处置 SOP",
    "实时信号异常，请推荐通知对象",
    "生成高峰拥挤预警和处置优先级",
    "实时客流密度达到临界值，请辅助研判",
]
GEO_CASES = [
    "绘制工作日上午通勤热力图",
    "生成居住区到核心商务区的 OD 热力图",
    "绘制各站客流空间热力图",
    "分析通勤主方向并生成热力图",
    "按区域聚合客流并输出 GIS 热力数据",
]
MULTIDIMENSIONAL_CASES = [
    "按票种、线路和小时统计周末客流，并找出学生票最集中时段",
    "统计学生票分线路分小时客流并排序",
    "比较成人票与学生票的小时客流贡献",
    "按票种和线路统计客流，找出最高组合",
    "查询老年票分线路客流并排序",
    "统计周末各票种小时客流并找出峰值",
    "按学生票、线路、小时生成多维客流表",
    "查询成人票使用最集中的线路和时段",
    "按票种统计客流贡献并排序",
    "生成票种、线路、小时三维统计并找出前五",
]
CORRELATION_CASES = [
    "分析客流变化与正点率之间的相关性",
    "分析进站量和设备故障率之间的关系",
    "计算客流与正点率的同期相关",
    "计算客流和运营指标的滞后相关",
    "分析出站量与设备故障率的相关性",
    "检查换乘量和正点率是否相关",
    "分析净流入与运营指标之间的统计关系",
    "比较客流、正点率和故障率的相关强度",
    "分析高峰客流变化与设备故障率之间的关系",
    "评估客流与正点率关系，明确不能证明因果",
]
DIAGNOSIS_CASES = [
    "昨天 1 号线晚高峰客流为什么下降",
    "昨天进站客流下降的原因是什么",
    "分析出站客流异常下降的可能原因",
    "为什么换乘量比平时低",
    "定位净流入下降的原因候选",
    "昨天晚高峰客流为什么变化",
    "客流骤降是否与设备异常有关，请做原因分析",
    "分析站点客流下降并列出证据缺口",
    "为什么昨天客流减少，给出反证和待补数据",
    "对客流下降建立原因假设树",
]
TREND_CASES = [
    "分析中长期客流趋势",
    "研判进站量短期趋势",
    "分析出站量中期变化趋势",
    "分解换乘量时间序列趋势",
    "研判净流入长期趋势和不确定性",
    "分析小时客流上升或下降趋势",
    "比较短期、中期、长期客流趋势",
    "生成客流趋势分解结果",
    "分析高峰客流未来变化趋势",
    "研判线网客流趋势并说明基线限制",
]


def main() -> int:
    cases: list[dict] = []

    def add(
        category: str,
        task_type: str,
        question: str,
        tools: list[str],
        *,
        evidence_kinds: list[str],
        artifact_required: bool = False,
        parameter: dict | None = None,
        human_gate: bool = False,
        non_causal: bool = False,
    ) -> None:
        case = {
            "case_id": f"assistant-{len(cases) + 1:03d}",
            "category": category,
            "question": question,
            "expected_task_type": task_type,
            "expected_tools": tools,
            "expected_status": "completed",
            "expected_evidence_kinds": evidence_kinds,
            "required_states": [
                "RECEIVE",
                "UNDERSTAND",
                "CLARIFY",
                "PLAN",
                "EXECUTE_TOOLS",
                "OBSERVE",
                "SYNTHESIZE",
                "VERIFY",
                "RESPOND",
            ],
            "artifact_required": artifact_required,
            "human_gate": human_gate,
            "non_causal": non_causal,
            "data_scope": "synthetic",
        }
        if parameter:
            case["expected_parameter"] = parameter
        cases.append(case)

    for question in QUERY_CASES:
        tools = ["query_metric"]
        if "排序" in question or "前三" in question:
            tools.append("rank_stations")
        add("natural_query", "query", question, tools, evidence_kinds=["fact"])

    for question in COMPARE_CASES:
        if "1 号线" in question:
            tools = ["query_metric", "compare_groups"]
            if "故障" in question:
                tools.extend(["get_operational_indicators", "calculate_correlation"])
        else:
            tools = ["compare_metric_periods"]
        add("multi_compare", "compare", question, tools, evidence_kinds=["fact"])

    for attendance in range(10_000, 110_000, 10_000):
        question = f"奥体中心有 {attendance // 10_000} 万人演唱会，预测附近站点客流并给出建议"
        add(
            "event_forecast",
            "forecast",
            question,
            [
                "find_similar_historical_days",
                "run_reference_day_forecast",
                "run_event_forecast",
                "compare_forecast_with_baseline",
                "search_operating_sop",
            ],
            evidence_kinds=["model_output", "knowledge"],
            parameter={"tool": "run_event_forecast", "name": "attendance", "value": attendance},
            human_gate=True,
        )

    for question in ALERT_CASES:
        add(
            "realtime_alert",
            "alert",
            question,
            [
                "detect_anomalies",
                "get_alert_thresholds",
                "search_operating_sop",
                "build_action_candidates",
            ],
            evidence_kinds=["statistic", "knowledge"],
            human_gate=True,
        )

    for report_name in (
        "昨日全线网日报",
        "早高峰日报",
        "晚高峰日报",
        "异常站点日报",
        "运营客流日报",
    ):
        add(
            "scheduled_report",
            "report",
            f"生成{report_name}，与上期比较并找出异常",
            ["query_metric", "compare_metric_periods", "detect_anomalies", "build_daily_report"],
            evidence_kinds=["fact", "statistic"],
            artifact_required=True,
        )

    for window in (10, 15, 20, 25, 30, 35, 40, 45, 60, 90):
        add(
            "network_transfer",
            "transfer",
            f"把轨道出站后 {window} 分钟内公交上车定义为换乘，统计各站换乘量",
            [
                "query_rail_transactions",
                "query_bus_transactions",
                "match_transfer_records",
                "calculate_transfer_flow",
            ],
            evidence_kinds=["fact"],
            parameter={
                "tool": "calculate_transfer_flow",
                "name": "window_minutes",
                "value": window,
            },
        )

    for question in GEO_CASES:
        add(
            "geo_heatmap",
            "geo",
            question,
            [
                "geocode_stations",
                "aggregate_flow_by_region",
                "build_od_heatmap",
                "build_commuting_profile",
            ],
            evidence_kinds=["chart"],
            artifact_required=True,
        )

    for question in MULTIDIMENSIONAL_CASES:
        add(
            "multidimensional_statistics",
            "query",
            question,
            ["query_ticket_flow", "rank_stations"],
            evidence_kinds=["statistic"],
        )

    for question in CORRELATION_CASES:
        add(
            "correlation",
            "correlation",
            question,
            [
                "query_metric",
                "get_operational_indicators",
                "calculate_correlation",
                "calculate_lagged_correlation",
            ],
            evidence_kinds=["statistic"],
            non_causal=True,
        )

    for question in DIAGNOSIS_CASES:
        add(
            "diagnosis",
            "diagnosis",
            question,
            ["query_metric", "get_operational_indicators", "diagnose_flow_change"],
            evidence_kinds=["fact"],
            non_causal=True,
        )

    for question in TREND_CASES:
        add(
            "trend",
            "trend",
            question,
            ["query_metric", "decompose_time_series"],
            evidence_kinds=["statistic"],
        )
    if len(cases) != 100:
        raise RuntimeError(f"expected 100 cases, generated {len(cases)}")
    OUTPUT.write_text(
        json.dumps({"schema_version": "1.0", "cases": cases}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(OUTPUT), "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
