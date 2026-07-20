#!/usr/bin/env python3
"""One-shot report runner for an external scheduler; it never installs a schedule itself."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.provider import FakeProvider
from metro_agent.assistant.schemas import AssistantMessageRequest

ROOT = Path(__file__).resolve().parents[1]


def run(task: str, output: Path) -> dict:
    runtime = output.parent / ".scheduled-assistant-runtime"
    service = SyntheticApiService(
        ApiSettings(
            metrics_path=ROOT / "examples/synthetic_data/metrics.json",
            data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
            audit_dir=runtime / "audits",
            environment="scheduled-local",
        )
    )
    assistant = AssistantService(service, runtime / "assistant", provider=FakeProvider())
    session_id = assistant.create_session()["session_id"]
    result = assistant.message(session_id, AssistantMessageRequest(message=task))
    if result["status"] != "completed" or not result["verification"]["valid"]:
        raise RuntimeError("scheduled assistant run did not pass verification")
    payload = {
        "schema_version": "1.0",
        "run_id": result["run_id"],
        "task": task,
        "data_scope": "synthetic",
        "answer": result["response"]["answer"],
        "evidence_refs": result["response"]["evidence_refs"],
        "artifact_refs": [
            artifact
            for tool_result in result["tool_results"]
            for artifact in tool_result["artifact_refs"]
        ],
        "verification": result["verification"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task",
        default="分析昨日全线网客流，找出异常站点，和上周同期比较，生成日报",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.task, args.output)
    print(json.dumps({"output": str(args.output), "run_id": result["run_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
