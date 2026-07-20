from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from metro_agent.api.service import SyntheticApiService
from metro_agent.assistant import prompts
from metro_agent.assistant.context_builder import ContextBuilder
from metro_agent.assistant.evidence import build_evidence_packet
from metro_agent.assistant.provider import (
    FakeProvider,
    HermesCodexProvider,
    LLMProvider,
    OpenAICompatibleProvider,
)
from metro_agent.assistant.schemas import (
    AssistantMessageRequest,
    AssistantResponse,
    DatasetEligibility,
    HumanFeedback,
    HumanFeedbackRequest,
    IntentEnvelope,
    RunRecord,
    TaskPlan,
    ToolResult,
)
from metro_agent.assistant.tool_registry import ToolRegistry
from metro_agent.assistant.trace_store import TraceStore
from metro_agent.assistant.verifier import verify_plan, verify_response


class AssistantService:
    def __init__(
        self,
        data_service: SyntheticApiService,
        root: Path,
        provider: LLMProvider | None = None,
    ) -> None:
        self.data_service = data_service
        self.trace_store = TraceStore(root / "traces")
        self.tools = ToolRegistry(data_service, root / "reports")
        self.context_builder = ContextBuilder(data_service, self.tools.names)
        self.provider = provider or provider_from_environment()
        self._message_lock = threading.RLock()

    def create_session(self) -> dict[str, Any]:
        return self.trace_store.create_session().model_dump(mode="json")

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.trace_store.get_run(run_id).model_dump(mode="json")

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        return self.trace_store.get_run(run_id).events

    def message(self, session_id: str, request: AssistantMessageRequest) -> dict[str, Any]:
        with self._message_lock:
            return self._message(session_id, request)

    def record_feedback(self, run_id: str, request: HumanFeedbackRequest) -> dict[str, Any]:
        with self._message_lock:
            run = self.trace_store.get_run(run_id)
            run.human_feedback.append(
                HumanFeedback(correction=request.correction, accepted=request.accepted)
            )
            if request.accepted and request.adopted_response is not None:
                run.adopted_response = request.adopted_response
                trajectory_valid = bool(
                    run.verification
                    and run.verification.valid
                    and run.evidence
                    and not run.evidence.missing_evidence
                    and run.tool_results
                    and all(result.status == "success" for result in run.tool_results)
                    and request.adopted_response.evidence_refs
                )
                run.dataset_eligibility = DatasetEligibility(
                    eligible=trajectory_valid,
                    reasons=(
                        ["human-confirmed final response and complete verified trajectory"]
                        if trajectory_valid
                        else ["human response recorded, but trajectory quality gates failed"]
                    ),
                    requires_human_confirmation=not trajectory_valid,
                )
            self._event(run, "HUMAN_FEEDBACK", "人工修正与采纳状态已记录")
            self.trace_store.save_run(run)
            return run.model_dump(mode="json")

    def _message(self, session_id: str, request: AssistantMessageRequest) -> dict[str, Any]:
        session = self.trace_store.get_session(session_id)
        context = self.context_builder.build(request.message, session.messages)
        run = RunRecord(
            run_id=f"run-{uuid.uuid4().hex}",
            session_id=session_id,
            provider=self.provider.name,
            original_question=request.message,
            selected_context={
                "business_dictionary": context["business_dictionary"],
                "catalog": context["catalog"],
                "available_tools": context["available_tools"],
                "recent_history": context["recent_history"],
                "data_scope": context["data_scope"],
            },
        )
        self._event(run, "RECEIVE", "用户问题已进入状态机")
        self.trace_store.save_run(run)
        try:
            self._event(run, "UNDERSTAND", "生成结构化 IntentEnvelope")
            intent = self.provider.generate_structured(
                prompts.UNDERSTAND_AND_PLAN,
                IntentEnvelope,
                context=context,
            )
            run.intent = intent
            context["intent"] = intent.model_dump(mode="json")
            self._event(run, "CLARIFY", "检查歧义和追问门")
            if intent.needs_clarification:
                questions = intent.ambiguities or ["请补充时间、线路、站点或指标范围。"]
                run.response = AssistantResponse(
                    answer="当前任务存在会显著影响执行结果的歧义，需要补充信息。",
                    limitations=["在歧义解决前未调用任何业务工具。"],
                    follow_up_questions=questions,
                )
                run.status = "needs_clarification"
                session.messages.extend(
                    [
                        {"role": "user", "content": request.message},
                        {"role": "assistant", "content": "；".join(questions)},
                    ]
                )
                self.trace_store.save_session(session)
                self.trace_store.save_run(run)
                return run.model_dump(mode="json")

            self._event(run, "PLAN", "生成受约束 TaskPlan")
            plan = self.provider.generate_tool_calls(prompts.UNDERSTAND_AND_PLAN, context=context)
            verify_plan(plan, set(self.tools.names))
            run.plan = plan
            self._event(run, "EXECUTE_TOOLS", f"执行 {len(plan.steps)} 个工具步骤")
            run.tool_results = self._execute_plan(plan, run)

            self._event(run, "OBSERVE", "汇总工具结果与证据缺口")
            evidence = build_evidence_packet(request.message, run.tool_results)
            if any(result.status != "success" for result in run.tool_results):
                self._event(run, "REPLAN", "存在失败或缺失证据，尝试一次受限重规划")
                extra = self._replan(context, plan, run.tool_results)
                if extra:
                    run.replans.append(extra)
                    run.tool_results.extend(self._execute_plan(extra, run))
                    evidence = build_evidence_packet(request.message, run.tool_results)
            run.evidence = evidence

            self._event(run, "SYNTHESIZE", "从 EvidencePacket 生成业务回答")
            response = self.provider.synthesize_from_evidence(
                request.message,
                evidence,
                context=context,
            )
            run.response = response
            self._event(run, "VERIFY", "核对证据引用、数字和失败步骤")
            run.verification = verify_response(response, evidence)
            if not run.verification.valid:
                raise ValueError("assistant response failed evidence verification")
            run.dataset_eligibility = DatasetEligibility(
                eligible=False,
                reasons=[
                    "structured trajectory passed; Gold Case or human confirmation still required"
                ],
                requires_human_confirmation=True,
            )
            run.status = "completed"
            self._event(run, "RESPOND", "回答已通过验证并保存轨迹")
            session.messages.extend(
                [
                    {"role": "user", "content": request.message},
                    {"role": "assistant", "content": response.answer},
                ]
            )
            self.trace_store.save_session(session)
            self.trace_store.save_run(run)
            return run.model_dump(mode="json")
        except (ValueError, TypeError, RuntimeError) as exc:
            run.status = "failed"
            self._event(run, "FAILED", _safe_failure(exc))
            self.trace_store.save_run(run)
            raise

    def _execute_plan(self, plan: TaskPlan, run: RunRecord) -> list[ToolResult]:
        pending = {step.step_id: step for step in plan.steps}
        completed: dict[str, ToolResult] = {}
        ordered: list[ToolResult] = []
        while pending:
            ready = [
                step
                for step in pending.values()
                if all(dependency in completed for dependency in step.depends_on)
            ]
            if not ready:
                raise ValueError("task plan dependency graph cannot make progress")
            executable = []
            for step in ready:
                dependencies = [completed[item] for item in step.depends_on]
                if any(item.status != "success" for item in dependencies):
                    result = ToolResult(
                        step_id=step.step_id,
                        tool=step.tool,
                        status="skipped",
                        warnings=["dependency failed"],
                    )
                    completed[step.step_id] = result
                    ordered.append(result)
                    pending.pop(step.step_id)
                else:
                    executable.append((step, dependencies))
            with ThreadPoolExecutor(max_workers=min(4, max(1, len(executable)))) as pool:
                futures = {
                    pool.submit(
                        self.tools.execute,
                        step.step_id,
                        step.tool,
                        step.arguments,
                        dependencies,
                    ): step
                    for step, dependencies in executable
                }
                batch: dict[str, ToolResult] = {}
                for future in as_completed(futures):
                    result = future.result()
                    batch[result.step_id] = result
                for step, _ in executable:
                    result = batch[step.step_id]
                    completed[step.step_id] = result
                    ordered.append(result)
                    pending.pop(step.step_id)
                    self._event(run, "TOOL_RESULT", f"{step.step_id}:{step.tool}:{result.status}")
        return ordered

    def _replan(
        self,
        context: dict[str, Any],
        original: TaskPlan,
        results: list[ToolResult],
    ) -> TaskPlan | None:
        replanned = self.provider.generate_tool_calls(
            prompts.OBSERVE_AND_REPLAN,
            context={
                **context,
                "original_plan": original.model_dump(mode="json"),
                "tool_results": [item.model_dump(mode="json") for item in results],
            },
        )
        existing = {(step.tool, _canonical(step.arguments)) for step in original.steps}
        novel = [
            step
            for step in replanned.steps
            if (step.tool, _canonical(step.arguments)) not in existing and not step.depends_on
        ]
        if not novel:
            return None
        normalized = [
            step.model_copy(update={"step_id": f"s{100 + index}", "depends_on": []})
            for index, step in enumerate(novel, start=1)
        ]
        plan = TaskPlan(
            plan_id=f"{original.plan_id}-replan",
            task_type=original.task_type,
            steps=normalized,
            expected_evidence=replanned.expected_evidence,
            answer_format=replanned.answer_format,
        )
        verify_plan(plan, set(self.tools.names))
        return plan

    @staticmethod
    def _event(run: RunRecord, state: str, detail: str) -> None:
        from datetime import UTC, datetime

        run.events.append(
            {"state": state, "detail": detail, "timestamp": datetime.now(UTC).isoformat()}
        )


def provider_from_environment() -> LLMProvider:
    mode = os.environ.get("METRO_ASSISTANT_PROVIDER", "fake").strip().lower()
    if mode == "fake":
        return FakeProvider()
    if mode == "openai":
        return OpenAICompatibleProvider(
            model=os.environ.get("METRO_ASSISTANT_MODEL", "gpt-5.6-sol"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
    if mode == "hermes-codex":
        return HermesCodexProvider(
            command=os.environ.get("METRO_ASSISTANT_HERMES_COMMAND", "hermes"),
            model=os.environ.get("METRO_ASSISTANT_MODEL", "gpt-5.6-sol"),
        )
    raise ValueError("METRO_ASSISTANT_PROVIDER must be fake, openai, or hermes-codex")


def _canonical(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_failure(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        return "provider_or_runtime_failure"
    return str(exc)[:200]
