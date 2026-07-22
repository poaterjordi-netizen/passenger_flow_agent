#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metro_agent.api.app import create_app
from metro_agent.assistant.schemas import AssistantMessageRequest


def _safe_egress(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep governance metadata only; never copy model payloads or production evidence."""

    allowed = {
        "purpose",
        "decision",
        "provider",
        "model",
        "endpoint_target_hash",
        "endpoint_binding_verified",
        "exact_payload_hash",
        "outbound_field_paths",
        "status",
    }
    return [{key: value for key, value in record.items() if key in allowed} for record in records]


def evaluate(question: str) -> dict[str, Any]:
    app = create_app()
    assistant = app.state.assistant
    session_id = assistant.create_session()["session_id"]
    run = assistant.message(session_id, AssistantMessageRequest(message=question))
    provider = assistant.provider
    usage = list(getattr(provider, "usage_records", []))
    tool_results = run.get("tool_results", [])
    egress = _safe_egress(run.get("model_egress", []))
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "production_shadow_local_codex",
        "data_scope": run.get("selected_context", {}).get("data_scope"),
        "assistant_status": app.state.assistant_status,
        "provider": run.get("provider"),
        "run_status": run.get("status"),
        "semantic_source": run.get("semantic_source"),
        "task_type": (run.get("intent") or {}).get("task_type"),
        "operation": (run.get("operation_ir") or {}).get("operation"),
        "tools": [
            {"tool": item.get("tool"), "status": item.get("status")}
            for item in tool_results
        ],
        "all_tools_succeeded": bool(tool_results)
        and all(item.get("status") == "success" for item in tool_results),
        "verification_valid": (run.get("verification") or {}).get("valid") is True,
        "model_runtime": run.get("model_runtime"),
        "model_egress": egress,
        "approved_model_calls": sum(
            item.get("decision") == "approved" and item.get("status") == "succeeded"
            for item in egress
        ),
        "usage": {
            "calls": len(usage),
            "input_tokens": sum(int(item.get("input_tokens", 0)) for item in usage),
            "output_tokens": sum(int(item.get("output_tokens", 0)) for item in usage),
            "reasoning_tokens": sum(int(item.get("reasoning_tokens", 0)) for item in usage),
            "total_tokens": sum(int(item.get("total_tokens", 0)) for item in usage),
            "elapsed_seconds": round(
                sum(float(item.get("elapsed_seconds", 0)) for item in usage), 3
            ),
            "cost_statuses": sorted(
                {str(item["cost_status"]) for item in usage if item.get("cost_status")}
            ),
        },
        "privacy_boundaries": [
            "No database credential, production row, evidence value, answer text, or SQL is copied into this report.",
            "Only endpoint binding, payload hashes, field paths, tool status, and aggregate usage are retained.",
            "This is local production-shadow evidence and never authorizes public production promotion.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded real-DB plus local-Codex shadow case and save metadata only."
    )
    parser.add_argument(
        "--question",
        default="查询2023年9月27日6点到7点进站客流最高的3个车站",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.question)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_status": report["run_status"],
                "data_scope": report["data_scope"],
                "all_tools_succeeded": report["all_tools_succeeded"],
                "verification_valid": report["verification_valid"],
                "approved_model_calls": report["approved_model_calls"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if (
        report["run_status"] == "completed"
        and report["data_scope"] == "production-shadow"
        and report["all_tools_succeeded"]
        and report["verification_valid"]
        and report["approved_model_calls"] >= 2
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
