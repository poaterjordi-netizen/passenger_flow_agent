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
from metro_agent.assistant.provider import HermesCodexProvider
from metro_agent.assistant.schemas import AssistantMessageRequest

ROOT = Path(__file__).resolve().parents[1]


def _expected_routes(case: dict[str, Any]) -> set[str]:
    value = case["expected_route"]
    return {value} if isinstance(value, str) else set(value)


def validate_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if payload.get("schema_version") != "1.0" or not isinstance(cases, list) or not cases:
        raise ValueError("semantic expression cases must be a non-empty version 1.0 fixture")
    required = {
        "case_id",
        "category",
        "messages",
        "expected_route",
        "expected_operations",
        "expected_target_kind",
        "expected_entity_types",
        "expected_status",
    }
    ids: set[str] = set()
    for case in cases:
        if set(case) != required:
            raise ValueError("semantic expression case fields do not match the contract")
        if case["case_id"] in ids:
            raise ValueError("semantic expression case ids must be unique")
        ids.add(case["case_id"])
        if not case["messages"] or not all(isinstance(item, str) and item for item in case["messages"]):
            raise ValueError("semantic expression messages must be non-empty strings")
        expected_routes = case["expected_route"]
        if isinstance(expected_routes, str):
            expected_routes = [expected_routes]
        if (
            not isinstance(expected_routes, list)
            or not expected_routes
            or not all(
                item in {"data", "general", "hybrid", "external", "clarify"}
                for item in expected_routes
            )
        ):
            raise ValueError("semantic expression route is invalid")
    return cases


def _evaluate_case(assistant: AssistantService, case: dict[str, Any]) -> dict[str, Any]:
    session_id = assistant.create_session()["session_id"]
    run: dict[str, Any] | None = None
    for message in case["messages"]:
        run = assistant.message(session_id, AssistantMessageRequest(message=message))
    assert run is not None
    frame = run.get("semantic_frame") or {}
    mentions = frame.get("entity_mentions") or []
    actual_types = [item.get("type") for item in mentions]
    expected_types = list(case["expected_entity_types"])
    expected_routes = _expected_routes(case)
    tools = [item["tool"] for item in run.get("tool_results", [])]
    semantic_route = frame.get("route")
    effective_route = (
        "clarify" if run.get("status") == "needs_clarification" else semantic_route
    )
    checks = {
        "route": semantic_route in expected_routes,
        "operations": bool(
            set(case["expected_operations"]) & set(frame.get("operations", []))
        ),
        "target_kind": frame.get("target_kind") == case["expected_target_kind"],
        "entity_mentions": all(actual_types.count(item) >= expected_types.count(item) for item in set(expected_types)),
        "status": run.get("status") == case["expected_status"],
        "no_incorrect_general_fallback": not (
            bool({"data", "hybrid"} & expected_routes)
            and semantic_route == "general"
        ),
        "database_execution": (
            bool(tools)
            if {"data", "hybrid"} & expected_routes
            and case["expected_status"] == "completed"
            else True
        ),
        "verified": (
            (run.get("verification") or {}).get("valid") is True
            if case["expected_status"] == "completed"
            else run.get("verification") is None
        ),
    }
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual_route": semantic_route,
        "effective_route": effective_route,
        "semantic_route_match": semantic_route in expected_routes,
        "effective_route_match": (
            effective_route == "clarify"
            if case["expected_status"] == "needs_clarification"
            else effective_route in expected_routes
        ),
        "actual_operations": frame.get("operations", []),
        "actual_target_kind": frame.get("target_kind"),
        "actual_status": run.get("status"),
        "semantic_source": run.get("semantic_source"),
        "model_calls": (run.get("model_runtime") or {}).get("model_calls", 0),
        "elapsed_seconds": (run.get("model_runtime") or {}).get("elapsed_seconds"),
    }


def evaluate(cases: list[dict[str, Any]], *, model: str, command: str, timeout: float) -> dict[str, Any]:
    provider = HermesCodexProvider(command=command, model=model, timeout=timeout)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="metro-semantic-eval-") as directory:
        temporary = Path(directory)
        service = SyntheticApiService(
            ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=temporary / "audits",
                environment="semantic-evaluation",
            )
        )
        assistant = AssistantService(service, temporary / "assistant", provider=provider)
        results = [_evaluate_case(assistant, case) for case in cases]
    total = len(results)
    passed = sum(item["passed"] for item in results)
    unnecessary = sum(
        item["effective_route"] == "clarify"
        and case["expected_status"] != "needs_clarification"
        for item, case in zip(results, cases, strict=True)
    )
    wrong_general = sum(
        item["actual_route"] == "general"
        and bool({"data", "hybrid"} & _expected_routes(case))
        for item, case in zip(results, cases, strict=True)
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": model,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "route_accuracy": sum(item["checks"]["route"] for item in results) / total,
            "semantic_route_accuracy": sum(
                item["semantic_route_match"] for item in results
            )
            / total,
            "effective_route_accuracy": sum(
                item["effective_route_match"] for item in results
            )
            / total,
            "entity_mention_recall": sum(item["checks"]["entity_mentions"] for item in results) / total,
            "unnecessary_clarification_rate": unnecessary / total,
            "incorrect_general_fallback_rate": wrong_general / total,
            "average_model_calls": sum(item["model_calls"] or 0 for item in results) / total,
        },
        "cases": results,
        "boundary": "synthetic data; report-only; not production accuracy evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GPT semantic compilation on open expressions")
    parser.add_argument("--cases", type=Path, default=ROOT / "examples/semantic_expression_cases.json")
    parser.add_argument("--all", action="store_true", help="Run all cases; each free message calls the model")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--hermes-command", default="hermes")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = validate_cases(args.cases)
    selected_ids = set(args.case_ids or [])
    selected = cases if args.all else [case for case in cases if case["case_id"] in selected_ids]
    if not selected:
        raise ValueError("select --all or at least one --case-id")
    report = evaluate(selected, model=args.model, command=args.hermes_command, timeout=args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
