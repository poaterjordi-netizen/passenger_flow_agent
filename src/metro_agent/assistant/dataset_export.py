from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from metro_agent.assistant.schemas import RunRecord

DATASET_FILES = {
    "intent": "intent_understanding.jsonl",
    "planning": "task_planning.jsonl",
    "tool_call": "tool_calling.jsonl",
    "evidence_response": "evidence_response.jsonl",
}


def export_verified_trajectories(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Export only explicitly eligible, fully verified trajectories into four datasets."""
    samples: dict[str, list[dict[str, Any]]] = {key: [] for key in DATASET_FILES}
    accepted_run_ids: list[str] = []
    rejected: dict[str, str] = {}
    for path in sorted(run_dir.rglob("run-*.json")):
        try:
            run = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rejected[path.name] = f"invalid_run:{type(exc).__name__}"
            continue
        reason = _rejection_reason(run)
        if reason:
            rejected[run.run_id] = reason
            continue
        assert run.intent is not None
        assert run.plan is not None
        assert run.evidence is not None
        assert run.response is not None
        accepted_run_ids.append(run.run_id)
        final_response = run.adopted_response or run.response
        samples["intent"].append(
            {
                "run_id": run.run_id,
                "input": {
                    "question": run.original_question,
                    "selected_context": run.selected_context,
                },
                "output": run.intent.model_dump(mode="json"),
            }
        )
        samples["planning"].append(
            {
                "run_id": run.run_id,
                "input": {
                    "question": run.original_question,
                    "selected_context": run.selected_context,
                    "intent": run.intent.model_dump(mode="json"),
                },
                "output": run.plan.model_dump(mode="json"),
            }
        )
        results_by_step = {result.step_id: result for result in run.tool_results}
        for step in run.plan.steps:
            samples["tool_call"].append(
                {
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "input": {
                        "intent": run.intent.model_dump(mode="json"),
                        "dependency_results": [
                            results_by_step[dependency].model_dump(mode="json")
                            for dependency in step.depends_on
                            if dependency in results_by_step
                        ],
                    },
                    "output": step.model_dump(mode="json"),
                }
            )
        samples["evidence_response"].append(
            {
                "run_id": run.run_id,
                "input": {
                    "question": run.original_question,
                    "evidence": run.evidence.model_dump(mode="json"),
                },
                "output": final_response.model_dump(mode="json"),
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    for kind, filename in DATASET_FILES.items():
        _atomic_write_jsonl(output_dir / filename, samples[kind])
    manifest = {
        "schema_version": "1.0",
        "accepted_runs": accepted_run_ids,
        "rejected_runs": rejected,
        "sample_counts": {kind: len(rows) for kind, rows in samples.items()},
        "policy": "eligible + verifier valid + all tools successful + no missing evidence + adopted/gold response",
    }
    _atomic_write_text(
        output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def _rejection_reason(run: RunRecord) -> str | None:
    if not run.dataset_eligibility.eligible:
        return "dataset_gate_not_passed"
    if run.verification is None or not run.verification.valid:
        return "verification_not_passed"
    if run.intent is None or run.plan is None or run.evidence is None or run.response is None:
        return "incomplete_trajectory"
    if any(result.status != "success" for result in run.tool_results):
        return "tool_failure_present"
    if run.evidence.missing_evidence:
        return "missing_evidence_present"
    if not run.response.evidence_refs:
        return "response_has_no_evidence_refs"
    if not run.dataset_eligibility.requires_human_confirmation and run.adopted_response is None:
        return "human_adoption_missing"
    return None


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
