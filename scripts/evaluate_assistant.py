#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.provider import FakeProvider
from metro_agent.assistant.schemas import AssistantMessageRequest

ROOT = Path(__file__).resolve().parents[1]


def evaluate(cases_path: Path) -> dict:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("assistant gold cases must contain a non-empty cases list")
    results = []
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        data_service = SyntheticApiService(
            ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=temporary / "audits",
                environment="evaluation",
            )
        )
        assistant = AssistantService(data_service, temporary / "assistant", provider=FakeProvider())
        for case in cases:
            session_id = assistant.create_session()["session_id"]
            run = assistant.message(
                session_id,
                AssistantMessageRequest(message=case["question"]),
            )
            tools = [item["tool"] for item in run["tool_results"]]
            expected_tools = set(case["expected_tools"])
            states = {item["state"] for item in run["events"]}
            evidence = run.get("evidence") or {}
            response = run.get("response") or {}
            verification = run.get("verification") or {}
            evidence_items = [
                item
                for key in (
                    "facts",
                    "statistics",
                    "charts",
                    "model_outputs",
                    "knowledge_sources",
                )
                for item in evidence.get(key, [])
            ]
            evidence_kinds = {item["kind"] for item in evidence_items}
            artifacts = [
                artifact for item in run["tool_results"] for artifact in item["artifact_refs"]
            ]
            parameter_ok = _parameter_matches(case.get("expected_parameter"), run.get("plan"))
            limitations = " ".join(response.get("limitations", []))
            checks = {
                "status": run["status"] == case["expected_status"],
                "task_type": run["intent"]["task_type"] == case["expected_task_type"],
                "required_tools": expected_tools.issubset(tools),
                "all_tools_succeeded": all(
                    item["status"] == "success" for item in run["tool_results"]
                ),
                "states": set(case["required_states"]).issubset(states),
                "verification": verification.get("valid") is True,
                "evidence": bool(response.get("evidence_refs")),
                "evidence_kinds": set(case["expected_evidence_kinds"]).issubset(evidence_kinds),
                "parameter": parameter_ok,
                "artifact": (
                    bool(artifacts) and all(Path(item).is_file() for item in artifacts)
                    if case["artifact_required"]
                    else True
                ),
                "human_gate": (
                    bool(response.get("recommendations"))
                    and all(
                        row.get("requires_confirmation") is True
                        for item in run["tool_results"]
                        for row in item["rows"]
                        if row.get("action")
                    )
                    if case["human_gate"]
                    else True
                ),
                "non_causal": ("因果" in limitations if case["non_causal"] else True),
                "trajectory_context": bool(run["selected_context"]),
                "dataset_gate": (
                    run["dataset_eligibility"]["eligible"] is False
                    and run["dataset_eligibility"]["requires_human_confirmation"] is True
                ),
            }
            results.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "passed": all(checks.values()),
                    "checks": checks,
                    "actual_task_type": run["intent"]["task_type"],
                    "tools": tools,
                    "evidence_kinds": sorted(evidence_kinds),
                    "dataset_candidate": all(checks.values()),
                }
            )
    passed = sum(item["passed"] for item in results)
    return {
        "schema_version": "1.0",
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "cases": results,
    }


def _parameter_matches(expected: dict | None, plan: dict | None) -> bool:
    if expected is None:
        return True
    if plan is None:
        return False
    for step in plan["steps"]:
        if step["tool"] == expected["tool"]:
            return step["arguments"].get(expected["name"]) == expected["value"]
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "examples/assistant_gold_cases.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.cases)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
