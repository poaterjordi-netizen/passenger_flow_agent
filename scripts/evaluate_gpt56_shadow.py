#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.provider import FakeProvider, HermesCodexProvider
from metro_agent.assistant.schemas import AssistantMessageRequest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_IDS = ["assistant-001", "assistant-021", "assistant-081"]


def _parameter_matches(expected: dict[str, Any] | None, plan: dict[str, Any] | None) -> bool:
    if expected is None:
        return True
    if plan is None:
        return False
    return any(
        step["tool"] == expected["tool"]
        and step["arguments"].get(expected["name"]) == expected["value"]
        for step in plan["steps"]
    )


def _checks(case: dict[str, Any], run: dict[str, Any]) -> dict[str, bool]:
    tools = [item["tool"] for item in run.get("tool_results", [])]
    states = {item["state"] for item in run.get("events", [])}
    evidence = run.get("evidence") or {}
    response = run.get("response") or {}
    verification = run.get("verification") or {}
    evidence_items = [
        item
        for key in ("facts", "statistics", "charts", "model_outputs", "knowledge_sources")
        for item in evidence.get(key, [])
    ]
    evidence_kinds = {item["kind"] for item in evidence_items}
    artifacts = [
        artifact
        for item in run.get("tool_results", [])
        for artifact in item.get("artifact_refs", [])
    ]
    limitations = " ".join(response.get("limitations", []))
    return {
        "status": run.get("status") == case["expected_status"],
        "task_type": (run.get("intent") or {}).get("task_type") == case["expected_task_type"],
        "required_tools": set(case["expected_tools"]).issubset(tools),
        "all_tools_succeeded": bool(run.get("tool_results"))
        and all(item["status"] == "success" for item in run["tool_results"]),
        "states": set(case["required_states"]).issubset(states),
        "verification": verification.get("valid") is True,
        "evidence": bool(response.get("evidence_refs")),
        "evidence_kinds": set(case["expected_evidence_kinds"]).issubset(evidence_kinds),
        "parameter": _parameter_matches(case.get("expected_parameter"), run.get("plan")),
        "artifact": (
            bool(artifacts) and all(Path(item).is_file() for item in artifacts)
            if case["artifact_required"]
            else True
        ),
        "human_gate": (
            bool(response.get("recommendations"))
            and all(
                row.get("requires_confirmation") is True
                for item in run.get("tool_results", [])
                for row in item.get("rows", [])
                if row.get("action")
            )
            if case["human_gate"]
            else True
        ),
        "non_causal": "因果" in limitations if case["non_causal"] else True,
    }


def _run_case(
    assistant: AssistantService, case: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        session_id = assistant.create_session()["session_id"]
        run = assistant.message(
            session_id,
            AssistantMessageRequest(message=case["question"]),
        )
        checks = _checks(case, run)
        return run, {
            "passed": all(checks.values()),
            "checks": checks,
            "status": run.get("status"),
            "actual_task_type": (run.get("intent") or {}).get("task_type"),
            "tools": [item["tool"] for item in run.get("tool_results", [])],
            "verification_errors": (run.get("verification") or {}).get("errors", []),
            "error_code": None,
        }
    except (ValueError, TypeError, RuntimeError) as exc:
        return None, {
            "passed": False,
            "checks": {},
            "status": "failed",
            "actual_task_type": None,
            "tools": [],
            "verification_errors": [],
            "error_code": type(exc).__name__,
        }


def _usage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "api_calls",
        "elapsed_seconds",
    )
    return {
        "calls": len(records),
        **{key: round(sum(float(item.get(key, 0)) for item in records), 3) for key in numeric},
        "records": records,
    }


def evaluate(
    cases_path: Path,
    *,
    case_ids: list[str],
    model: str,
    hermes_command: str,
    timeout: float,
) -> dict[str, Any]:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    by_id = {case["case_id"]: case for case in payload.get("cases", [])}
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise ValueError(f"unknown case ids: {', '.join(missing)}")
    cases = [by_id[case_id] for case_id in case_ids]
    model_provider = HermesCodexProvider(
        command=hermes_command,
        model=model,
        timeout=timeout,
    )
    results = []
    with tempfile.TemporaryDirectory(prefix="metro-gpt56-shadow-") as directory:
        temporary = Path(directory)
        data_service = SyntheticApiService(
            ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=temporary / "audits",
                environment="gpt56-shadow",
            )
        )
        baseline = AssistantService(
            data_service,
            temporary / "baseline",
            provider=FakeProvider(),
        )
        candidate = AssistantService(
            data_service,
            temporary / "candidate",
            provider=model_provider,
        )
        for case in cases:
            _, baseline_result = _run_case(baseline, case)
            usage_start = len(model_provider.usage_records)
            _, candidate_result = _run_case(candidate, case)
            case_usage = model_provider.usage_records[usage_start:]
            results.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "question": case["question"],
                    "baseline": baseline_result,
                    "candidate": candidate_result,
                    "candidate_usage": _usage_summary(case_usage),
                }
            )
    baseline_passed = sum(item["baseline"]["passed"] for item in results)
    candidate_passed = sum(item["candidate"]["passed"] for item in results)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "synthetic_local_shadow",
        "provider": "openai-codex",
        "model": model,
        "selected_case_ids": case_ids,
        "summary": {
            "total": len(results),
            "baseline_passed": baseline_passed,
            "candidate_passed": candidate_passed,
            "candidate_failed": len(results) - candidate_passed,
            "promotion_allowed": False,
            "decision": "report_only",
        },
        "usage": _usage_summary(model_provider.usage_records),
        "cases": results,
        "boundaries": [
            "Synthetic fixtures only; this is not production accuracy evidence.",
            "The deterministic provider remains the protected default.",
            "No credential value is copied into the project or report.",
            "A full 100-case run requires explicit --all because it makes many real model calls.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare the deterministic baseline with real GPT-5.6-sol via Hermes OAuth."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "examples/assistant_gold_cases.json",
    )
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--all", action="store_true", help="Run all Gold Cases (many real calls).")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--hermes-command", default="hermes")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    all_ids = [case["case_id"] for case in payload.get("cases", [])]
    selected = all_ids if args.all else (args.case_ids or DEFAULT_CASE_IDS)
    report = evaluate(
        args.cases,
        case_ids=selected,
        model=args.model,
        hermes_command=args.hermes_command,
        timeout=args.timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["candidate_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
