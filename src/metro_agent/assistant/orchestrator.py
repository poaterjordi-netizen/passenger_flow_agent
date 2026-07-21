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
    AssistantCapabilities,
    AssistantMessageRequest,
    AssistantResponse,
    DatasetEligibility,
    HumanFeedback,
    HumanFeedbackRequest,
    IntentEnvelope,
    ModelRuntime,
    RunRecord,
    TaskPlan,
    ToolResult,
)
from metro_agent.assistant.tool_registry import ToolRegistry
from metro_agent.assistant.trace_store import TraceStore
from metro_agent.assistant.verifier import verify_intent, verify_plan, verify_response


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

    def capabilities(self) -> dict[str, Any]:
        return AssistantCapabilities.model_validate(
            {
                "implementation_status": "local_governed_prototype",
                "data_scope": "synthetic",
                "active_runtime": _provider_runtime(self.provider),
                "architecture": [
                    {
                        "id": "understand",
                        "label": "意图理解",
                        "owner": "llm",
                        "detail": "生成候选意图；关键字段必须与 catalog-aware protected reference 一致。",
                    },
                    {
                        "id": "plan",
                        "label": "受约束规划",
                        "owner": "llm",
                        "detail": "生成候选 TaskPlan；工具、顺序和参数漂移会在执行前被拒绝。",
                    },
                    {
                        "id": "execute",
                        "label": "确定性执行",
                        "owner": "deterministic",
                        "detail": "查询、统计、预测基线、相关和 GIS 数字均由工具产生。",
                    },
                    {
                        "id": "evidence",
                        "label": "证据封装",
                        "owner": "deterministic",
                        "detail": "工具结果转为 EvidencePacket 和可追溯 evidence_id。",
                    },
                    {
                        "id": "synthesize",
                        "label": "证据化回答",
                        "owner": "llm",
                        "detail": "模型只根据已产生的证据组织业务语言。",
                    },
                    {
                        "id": "verify",
                        "label": "回答核验",
                        "owner": "deterministic",
                        "detail": "检查证据引用、数字支持、失败步骤和有限数。",
                    },
                    {
                        "id": "human_gate",
                        "label": "人工确认",
                        "owner": "human",
                        "detail": "通知、处置、数据采纳和生产动作保留人工责任门。",
                    },
                ],
                "model_responsibilities": [
                    "生成自然语言意图候选并抽取业务实体",
                    "生成受 protected baseline 约束的结构化计划候选",
                    "根据 EvidencePacket 组织可读回答",
                ],
                "deterministic_controls": [
                    "catalog-aware protected intent hard match",
                    "allowlisted protected TaskPlan exact argument gate",
                    "参数化确定性工具和自由 SQL 禁止",
                    "EvidencePacket 引用与数字支持校验",
                    "完整状态机和审计轨迹",
                ],
                "prohibited_model_actions": [
                    "保存或替代权威客流事实库",
                    "生成任意 SQL 并直接执行",
                    "自行决定权限、通知或运营处置",
                    "绕过工具白名单、verifier 或人工确认门",
                ],
                "validated_milestones": [
                    {
                        "id": "deterministic_gold",
                        "label": "离线受治理 Gold Cases",
                        "status": "partial",
                        "evidence": "100/100",
                        "scope": "历史静态验证记录；当前 API 未回读带哈希 artifact，且不代表生产准确率。",
                    },
                    {
                        "id": "gpt56_shadow",
                        "label": "真实 GPT-5.6-sol shadow",
                        "status": "partial",
                        "evidence": "3/3",
                        "scope": "历史 report-only 记录；当前 API 未回读原始 usage artifact，不代表在线准入。",
                    },
                    {
                        "id": "http_smoke",
                        "label": "真实 FastAPI 模型链路",
                        "status": "partial",
                        "evidence": "HTTP 200",
                        "scope": "历史 smoke 记录；未作为当前进程运行时健康证明。",
                    },
                    {
                        "id": "production",
                        "label": "生产模型与真实数据",
                        "status": "not_started",
                        "evidence": "待准入",
                        "scope": "内网端点、密钥管理、权威数据、RBAC/ABAC 和业务准确率尚未验收。",
                    },
                ],
                "production_gaps": [
                    "历史验证里程碑尚未接入带哈希、可回读的运行时 artifact manifest",
                    "100 条真实模型 Gold Cases 尚未执行，尚未证明相对基线有净增益",
                    "生产 OpenAI-compatible 端点与 secret manager 尚未联调",
                    "权威生产数据、正式权限和真实预测准确率尚未验收",
                    "自动通知、5 分钟调度和运营联动仍受人工闸门保护",
                ],
            }
        ).model_dump(mode="json")

    def message(self, session_id: str, request: AssistantMessageRequest) -> dict[str, Any]:
        with self._message_lock:
            return self._message(session_id, request)

    def record_feedback(self, run_id: str, request: HumanFeedbackRequest) -> dict[str, Any]:
        with self._message_lock:
            run = self.trace_store.get_run(run_id)
            adopted_verification = None
            if request.accepted and request.adopted_response is not None:
                if run.evidence is None:
                    raise ValueError("cannot adopt a response without an evidence packet")
                adopted_verification = verify_response(request.adopted_response, run.evidence)
                if not adopted_verification.valid:
                    raise ValueError("adopted response failed evidence verification")
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
                    and adopted_verification
                    and adopted_verification.valid
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
        provider_calls = 0
        usage_offset = len(getattr(self.provider, "usage_records", []))
        run = RunRecord(
            run_id=f"run-{uuid.uuid4().hex}",
            session_id=session_id,
            provider=self.provider.name,
            model_runtime=_provider_runtime(self.provider),
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
            protected_intent = FakeProvider().generate_structured(
                prompts.UNDERSTAND_AND_PLAN,
                IntentEnvelope,
                context=context,
            )
            context["protected_reference_intent"] = protected_intent.model_dump(mode="json")
            provider_calls += 1
            intent = self.provider.generate_structured(
                prompts.UNDERSTAND_AND_PLAN,
                IntentEnvelope,
                context=context,
            )
            verify_intent(intent, protected_intent)
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
                run.model_runtime = _provider_runtime(
                    self.provider,
                    provider_calls=provider_calls,
                    usage_offset=usage_offset,
                )
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
            protected_plan = FakeProvider().generate_tool_calls(
                prompts.UNDERSTAND_AND_PLAN,
                context=context,
            )
            context["protected_reference_plan"] = protected_plan.model_dump(mode="json")
            provider_calls += 1
            plan = self.provider.generate_tool_calls(prompts.UNDERSTAND_AND_PLAN, context=context)
            verify_plan(plan, set(self.tools.names), protected_plan)
            run.plan = plan
            self._event(run, "EXECUTE_TOOLS", f"执行 {len(plan.steps)} 个工具步骤")
            run.tool_results = self._execute_plan(plan, run)

            self._event(run, "OBSERVE", "汇总工具结果与证据缺口")
            evidence = build_evidence_packet(request.message, run.tool_results)
            if any(result.status != "success" for result in run.tool_results):
                self._event(run, "REPLAN", "存在失败或缺失证据，尝试一次受限重规划")
                provider_calls += 1
                extra = self._replan(context, plan, run.tool_results)
                if extra:
                    run.replans.append(extra)
                    run.tool_results.extend(self._execute_plan(extra, run))
                    evidence = build_evidence_packet(request.message, run.tool_results)
            run.evidence = evidence

            self._event(run, "SYNTHESIZE", "从 EvidencePacket 生成业务回答")
            provider_calls += 1
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
            run.model_runtime = _provider_runtime(
                self.provider,
                provider_calls=provider_calls,
                usage_offset=usage_offset,
            )
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
            run.model_runtime = _provider_runtime(
                self.provider,
                provider_calls=provider_calls,
                usage_offset=usage_offset,
            )
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
        failed_root_steps = {
            (step.tool, _canonical(step.arguments)): step
            for step in original.steps
            if not step.depends_on
            and any(result.step_id == step.step_id and result.status == "failed" for result in results)
        }
        accepted_keys: list[tuple[str, str]] = []
        for step in replanned.steps:
            key = (step.tool, _canonical(step.arguments))
            if step.depends_on or key not in failed_root_steps or key in accepted_keys:
                continue
            accepted_keys.append(key)
        if not accepted_keys:
            return None
        normalized = [
            failed_root_steps[key].model_copy(
                update={"step_id": f"s{100 + index}", "depends_on": []}
            )
            for index, key in enumerate(accepted_keys, start=1)
        ]
        plan = TaskPlan(
            plan_id=f"{original.plan_id}-replan",
            task_type=original.task_type,
            steps=normalized,
            expected_evidence=original.expected_evidence,
            answer_format=original.answer_format,
        )
        protected_retry = TaskPlan(
            plan_id=f"{original.plan_id}-protected-retry",
            task_type=original.task_type,
            steps=normalized,
            expected_evidence=original.expected_evidence,
            answer_format=original.answer_format,
        )
        verify_plan(plan, set(self.tools.names), protected_retry)
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


def _provider_runtime(
    provider: LLMProvider,
    *,
    provider_calls: int = 0,
    usage_offset: int = 0,
) -> ModelRuntime:
    model = getattr(provider, "model", None)
    if isinstance(provider, HermesCodexProvider):
        mode = "local_governed_model"
        execution_role = "model_active"
        real_model_configured = True
    elif isinstance(provider, OpenAICompatibleProvider):
        mode = "openai_compatible"
        execution_role = "model_active"
        real_model_configured = True
    else:
        mode = "offline_deterministic"
        execution_role = "deterministic_active"
        real_model_configured = False

    usage_records = list(getattr(provider, "usage_records", []))[usage_offset:]

    def summed(key: str) -> int | None:
        values = [
            record.get(key)
            for record in usage_records
            if isinstance(record.get(key), int)
            and not isinstance(record.get(key), bool)
            and record.get(key) >= 0
        ]
        return sum(values) if values else None

    elapsed_values = [
        record.get("elapsed_seconds")
        for record in usage_records
        if isinstance(record.get("elapsed_seconds"), (int, float))
        and not isinstance(record.get("elapsed_seconds"), bool)
        and record.get("elapsed_seconds") >= 0
    ]
    reported_model_calls = summed("api_calls") or 0
    failed_calls = sum(record.get("failed") is True for record in usage_records)
    completed_calls = sum(record.get("completed") is True for record in usage_records)
    if not real_model_configured:
        invocation_status = "not_applicable"
        usage_reporting = "not_applicable"
    elif not usage_records:
        invocation_status = "configured"
        usage_reporting = "unavailable"
    elif failed_calls and completed_calls:
        invocation_status = "partial"
        usage_reporting = "partial"
    elif failed_calls:
        invocation_status = "failed"
        usage_reporting = (
            "partial"
            if any(
                summed(key) is not None for key in ("input_tokens", "output_tokens", "total_tokens")
            )
            else "unavailable"
        )
    else:
        invocation_status = "succeeded"
        token_fields = ("input_tokens", "output_tokens", "total_tokens")
        usage_reporting = (
            "complete" if all(summed(key) is not None for key in token_fields) else "partial"
        )
    return ModelRuntime(
        provider=provider.name,
        model=model,
        mode=mode,
        execution_role=execution_role,
        real_model_configured=real_model_configured,
        real_model_active=reported_model_calls > 0,
        invocation_status=invocation_status,
        usage_reporting=usage_reporting,
        provider_calls=provider_calls,
        model_calls=reported_model_calls,
        input_tokens=summed("input_tokens"),
        output_tokens=summed("output_tokens"),
        reasoning_tokens=summed("reasoning_tokens"),
        total_tokens=summed("total_tokens"),
        elapsed_seconds=round(sum(elapsed_values), 3) if elapsed_values else None,
    )


def _canonical(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_failure(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        return "provider_or_runtime_failure"
    return str(exc)[:200]
