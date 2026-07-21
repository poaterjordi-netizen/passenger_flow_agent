from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def summarize_failure_traces(trace_root: Path) -> dict[str, Any]:
    """Cluster persisted run failures into reviewable regression-test candidates."""

    run_dir = trace_root / "runs" if (trace_root / "runs").is_dir() else trace_root
    clusters: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    scanned = 0
    for path in sorted(run_dir.glob("run-*.json")):
        payload = _read_object(path)
        if payload is None:
            continue
        scanned += 1
        status = str(payload.get("status") or "unknown")
        if status == "completed":
            continue
        operation = str((payload.get("operation_ir") or {}).get("operation") or "unknown")
        capability = str((payload.get("capability_match") or {}).get("capability_id") or "none")
        category = str(payload.get("failure_category") or _infer_category(payload))
        question = str(payload.get("original_question") or "")
        tool_errors = sorted(
            {
                str(item.get("error_code"))
                for item in payload.get("tool_results", [])
                if item.get("error_code")
            }
        )
        clusters[(category, operation, capability)].append(
            {
                "run_id": payload.get("run_id"),
                "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
                "sample_question": question,
                "status": status,
                "tool_error_codes": tool_errors,
            }
        )

    rows = []
    category_counts: Counter[str] = Counter()
    for (category, operation, capability), samples in sorted(
        clusters.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        category_counts[category] += len(samples)
        rows.append(
            {
                "failure_category": category,
                "operation": operation,
                "capability_id": capability,
                "count": len(samples),
                "tool_error_codes": sorted(
                    {code for sample in samples for code in sample["tool_error_codes"]}
                ),
                "examples": samples[:5],
                "regression_candidate": {
                    "question": samples[0]["sample_question"],
                    "expected_operation": operation,
                    "expected_capability": capability,
                    "expected_not_failure_category": category,
                },
            }
        )
    return {
        "schema_version": "1.0",
        "scanned_run_count": scanned,
        "failed_or_clarified_run_count": sum(category_counts.values()),
        "category_counts": dict(sorted(category_counts.items())),
        "clusters": rows,
    }


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _infer_category(payload: dict[str, Any]) -> str:
    if payload.get("status") == "needs_clarification":
        return "material_ambiguity"
    tool_errors = {
        item.get("error_code") for item in payload.get("tool_results", []) if item.get("error_code")
    }
    if "forbidden" in tool_errors:
        return "authorization_failure"
    if "unknown_tool" in tool_errors:
        return "capability_gap"
    if tool_errors:
        return "tool_failure"
    events = " ".join(str(item.get("detail") or "") for item in payload.get("events", []))
    return "model_failure" if "provider_or_runtime_failure" in events else "data_unavailable"
