from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from metro_agent.access import AccessContext, AuthorizationService
from metro_agent.api.service import PassengerFlowDataService
from metro_agent.assistant import prompts
from metro_agent.assistant.capabilities import CapabilityRegistry
from metro_agent.assistant.context_builder import ContextBuilder
from metro_agent.assistant.evidence import build_evidence_packet
from metro_agent.assistant.operation_ir import OperationCompiler
from metro_agent.assistant.provider import (
    FakeProvider,
    HermesCodexProvider,
    LLMProvider,
    OpenAICompatibleProvider,
    provider_endpoint_identity,
)
from metro_agent.assistant.schemas import (
    AssistantCapabilities,
    AssistantMessageRequest,
    AssistantResponse,
    CapabilityMatch,
    DatasetEligibility,
    EvidencePacket,
    HumanFeedback,
    HumanFeedbackRequest,
    IntentEnvelope,
    ModelEgressRecord,
    ModelRuntime,
    RunRecord,
    TaskPlan,
    ToolStep,
    ToolResult,
)
from metro_agent.assistant.tool_registry import ToolRegistry
from metro_agent.assistant.trace_store import TraceRepository, TraceStore
from metro_agent.assistant.verifier import (
    verify_candidate_intent,
    verify_evidence_packet,
    verify_plan,
    verify_response,
)


class AssistantService:
    def __init__(
        self,
        data_service: PassengerFlowDataService,
        root: Path,
        provider: LLMProvider | None = None,
        trace_repository: TraceRepository | None = None,
        default_access_context: AccessContext | None = None,
        production_enabled: bool = False,
    ) -> None:
        self.data_service = data_service
        self.trace_store = trace_repository or TraceStore(root / "traces")
        self.tools = ToolRegistry(data_service, root / "reports")
        self.capability_registry = CapabilityRegistry()
        self.operation_compiler = OperationCompiler(self.capability_registry)
        self.context_builder = ContextBuilder(
            data_service, self.tools.names, self.capability_registry
        )
        self.provider = provider or provider_from_environment()
        self.default_access_context = default_access_context
        self.production_enabled = production_enabled
        self._message_lock = threading.RLock()

    def _access(self, access_context: AccessContext | None) -> AccessContext:
        context = access_context or self.default_access_context
        if context is None and self.data_service.data_scope == "synthetic":
            return AccessContext.synthetic_local()
        if context is None:
            raise PermissionError("production assistant requires a trusted access context")
        return context

    def create_session(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = self._access(access_context)
        self._require_production_gate()
        return self.trace_store.create_session(context).model_dump(mode="json")

    def get_run(self, run_id: str, access_context: AccessContext | None = None) -> dict[str, Any]:
        context = self._access(access_context)
        return self.trace_store.get_run(run_id, context).model_dump(mode="json")

    def get_events(
        self, run_id: str, access_context: AccessContext | None = None
    ) -> list[dict[str, Any]]:
        context = self._access(access_context)
        return self.trace_store.get_run(run_id, context).events

    def capabilities(self, access_context: AccessContext | None = None) -> dict[str, Any]:
        self._access(access_context)
        return AssistantCapabilities.model_validate(
            {
                "implementation_status": "local_governed_prototype",
                "data_scope": self.data_service.data_scope,
                "active_runtime": _provider_runtime(self.provider),
                "capability_registry_version": self.capability_registry.registry_version,
                "operation_capabilities": self.capability_registry.public_definitions(
                    self.data_service.data_scope, set(self.tools.names)
                ),
                "architecture": [
                    {
                        "id": "understand",
                        "label": "意图理解",
                        "owner": "deterministic",
                        "detail": "高置信规则直接解析；仅在规则 abstain 且策略允许时让模型选择候选。",
                    },
                    {
                        "id": "plan",
                        "label": "受约束规划",
                        "owner": "deterministic",
                        "detail": "Intent 先编译为 OperationIR，再由版本化能力注册表映射到受控工具。",
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
                        "detail": "目录与清单零模型渲染；复杂分析才由模型基于 EvidencePacket 组织语言。",
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
                    "在确定性解析 abstain 时对受控候选意图消歧",
                    "仅在数据出域策略明确批准时根据 EvidencePacket 组织可读回答",
                ],
                "deterministic_controls": [
                    "catalog、权限、版本、时间和实体硬校验",
                    "确定性 planner 与物理裁剪后的工具白名单",
                    "参数化确定性工具和自由 SQL 禁止",
                    "完整性、截断、EvidencePacket 引用与数字支持校验",
                    "OperationIR、能力注册表和 CoverageEvidence 覆盖语义校验",
                    "session/run/audit owner 与访问范围哈希",
                    "模型数据出域策略和字段摘要审计",
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
                    "production-shadow 不等于 production-readonly 准入",
                ],
            }
        ).model_dump(mode="json")

    def message(
        self,
        session_id: str,
        request: AssistantMessageRequest,
        access_context: AccessContext | None = None,
    ) -> dict[str, Any]:
        context = self._access(access_context)
        self._require_production_gate()
        with self._message_lock:
            return self._message(session_id, request, context)

    def record_feedback(
        self,
        run_id: str,
        request: HumanFeedbackRequest,
        access_context: AccessContext | None = None,
    ) -> dict[str, Any]:
        context = self._access(access_context)
        with self._message_lock:
            run = self.trace_store.get_run(run_id, context)
            adopted_verification = None
            if request.accepted and request.adopted_response is not None:
                if run.evidence is None:
                    raise ValueError("cannot adopt a response without an evidence packet")
                adopted_verification = verify_response(
                    request.adopted_response,
                    run.evidence,
                    allow_general_knowledge=bool(
                        run.operation_ir and run.operation_ir.answer_policy == "llm_general"
                    ),
                )
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
            self.trace_store.save_run(run, context)
            return run.model_dump(mode="json")

    def _message(
        self, session_id: str, request: AssistantMessageRequest, access_context: AccessContext
    ) -> dict[str, Any]:
        session = self.trace_store.get_session(session_id, access_context)
        context = self.context_builder.build(request.message, session.messages, access_context)
        provider_calls = 0
        usage_offset = len(getattr(self.provider, "usage_records", []))
        run = RunRecord(
            run_id=f"run-{uuid.uuid4().hex}",
            session_id=session_id,
            provider=self.provider.name,
            owner_subject_id=access_context.subject_id,
            owner_tenant_or_department=access_context.tenant_or_department,
            access_scope_hash=access_context.scope_hash(),
            policy_snapshot_id=access_context.policy_snapshot_id,
            model_runtime=_provider_runtime(self.provider),
            original_question=request.message,
            selected_context={
                "business_dictionary": context["business_dictionary"],
                "catalog": context["catalog"],
                "available_tools": context["available_tools"],
                "capability_registry": context["capability_registry"],
                "recent_history": context["recent_history"],
                "data_scope": context["data_scope"],
                "data_quality": context["data_quality"],
                "query_defaults": context["query_defaults"],
                "prompt_manifest": prompts.manifest(),
                "authorization": context["authorization"],
            },
        )
        self._event(run, "RECEIVE", "用户问题已进入状态机")
        self.trace_store.save_run(run, access_context)
        try:
            self._event(run, "UNDERSTAND", "确定性解析或受控模型候选路由")
            protected_intent = FakeProvider().generate_structured(
                prompts.INTENT_PARSER,
                IntentEnvelope,
                context=context,
            )
            deterministic_route = (
                "clarification"
                if protected_intent.needs_clarification or protected_intent.ambiguities
                else "confident"
                if self.operation_compiler.is_high_confidence(request.message, protected_intent)
                else "abstain"
            )
            if deterministic_route == "confident":
                intent = protected_intent
                run.intent_route = "deterministic"
            elif deterministic_route == "clarification":
                intent = protected_intent
                run.intent_route = "clarification"
            else:
                endpoint_identity = provider_endpoint_identity(self.provider)
                intent_context = _intent_outbound_context(context, protected_intent)
                intent_prompt = (
                    f"{prompts.INTENT_PARSER}\n"
                    "Propose one candidate within candidate_domain. Do not invent catalog "
                    "entities or permissions. immutable_scope is server-owned and will be locked."
                )
                allowed = _may_call_model(
                    access_context,
                    self.data_service.data_scope,
                    self.provider,
                    endpoint_identity,
                )
                call_index = self._start_model_egress(
                    run,
                    access_context,
                    purpose="intent_candidate",
                    prompt=intent_prompt,
                    outbound_context=intent_context,
                    schema=IntentEnvelope,
                    endpoint_identity=endpoint_identity,
                    allowed=allowed,
                )
                if allowed:
                    provider_calls += 1
                    try:
                        candidate = self.provider.generate_structured(
                            intent_prompt,
                            IntentEnvelope,
                            context=intent_context,
                        )
                    except Exception:
                        self._finish_model_egress(run, access_context, call_index, "failed")
                        raise
                    self._finish_model_egress(run, access_context, call_index, "succeeded")
                    intent = _lock_protected_intent(candidate, protected_intent)
                    verify_candidate_intent(intent, context["catalog"], access_context)
                    run.intent_route = "model_candidate"
                else:
                    intent = protected_intent.model_copy(
                        update={
                            "needs_clarification": True,
                            "ambiguities": [
                                *protected_intent.ambiguities,
                                "确定性解析置信度不足，且 Intent 出域策略或端点绑定未批准。",
                            ],
                        }
                    )
                    run.intent_route = "clarification"
            intent = _apply_relative_period_availability_gate(
                intent, request.message, context["catalog"]
            )
            verify_candidate_intent(intent, context["catalog"], access_context)
            run.intent = intent
            context["intent"] = intent.model_dump(mode="json")
            operation = self.operation_compiler.compile(
                request.message,
                intent,
                route_confidence=(
                    "model_candidate" if run.intent_route == "model_candidate" else "high"
                ),
            )
            capability_match = self.capability_registry.match(
                operation,
                data_scope=self.data_service.data_scope,
                available_tools=set(self.tools.names),
            )
            if capability_match.status == "matched":
                operation = operation.model_copy(
                    update={"answer_policy": capability_match.answer_policy}
                )
            elif capability_match.status == "missing_slots":
                slot_labels = {"origin": "起点", "destination": "终点"}
                missing_text = "、".join(
                    slot_labels.get(slot, slot) for slot in capability_match.missing_slots
                )
                intent = intent.model_copy(
                    update={
                        "needs_clarification": True,
                        "ambiguities": [
                            *intent.ambiguities,
                            f"任务缺少会改变执行结果的必要字段：{missing_text}。",
                        ],
                    }
                )
                run.intent = intent
                context["intent"] = intent.model_dump(mode="json")
                run.failure_category = "material_ambiguity"
            run.operation_ir = operation
            run.capability_match = capability_match
            context["operation_ir"] = operation.model_dump(mode="json")
            context["capability_match"] = capability_match.model_dump(mode="json")
            self._event(
                run,
                "COMPILE_OPERATION",
                f"{operation.operation}:{capability_match.status}:"
                f"{capability_match.capability_id or 'none'}",
            )
            self._event(run, "CLARIFY", "检查歧义和追问门")
            if intent.needs_clarification:
                questions = intent.ambiguities or ["请补充时间、线路、站点或指标范围。"]
                run.response = AssistantResponse(
                    answer="当前任务存在会显著影响执行结果的歧义，需要补充信息。",
                    limitations=["在歧义解决前未调用任何业务工具。"],
                    follow_up_questions=questions,
                )
                run.status = "needs_clarification"
                run.failure_category = run.failure_category or "material_ambiguity"
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
                self.trace_store.save_session(session, access_context)
                self.trace_store.save_run(run, access_context)
                return run.model_dump(mode="json")

            self._event(run, "PLAN", "确定性 planner 根据已验证 Intent 生成 TaskPlan")
            plan = FakeProvider().generate_tool_calls(
                prompts.TOOL_PLANNER,
                context=context,
            )
            unavailable_tools = sorted({step.tool for step in plan.steps} - set(self.tools.names))
            if unavailable_tools:
                self._event(
                    run,
                    "CAPABILITY_FALLBACK",
                    "原任务依赖未准入能力，改为执行受控能力准入检查",
                )
                plan = _capability_readiness_plan(intent)
                operation = operation.model_copy(update={"answer_policy": "deterministic_summary"})
                run.operation_ir = operation
                run.capability_match = _readiness_capability_match(
                    self.capability_registry, self.data_service.data_scope, set(self.tools.names)
                )
                context["operation_ir"] = operation.model_dump(mode="json")
                context["capability_match"] = run.capability_match.model_dump(mode="json")
            verify_plan(plan, set(self.tools.names))
            _verify_plan_capability(plan, run.capability_match)
            run.plan = plan
            self._event(run, "EXECUTE_TOOLS", f"执行 {len(plan.steps)} 个工具步骤")
            run.tool_results = self._execute_plan(plan, run, access_context)

            self._event(run, "OBSERVE", "汇总工具结果与证据缺口")
            effective_results = run.tool_results
            evidence = build_evidence_packet(request.message, effective_results)
            if any(result.status != "success" for result in run.tool_results):
                self._event(run, "REPLAN", "存在失败或缺失证据，尝试一次受限重规划")
                extra = self._replan(context, plan, run.tool_results)
                if extra:
                    run.replans.append(extra)
                    retry_results = self._execute_plan(extra, run, access_context)
                    run.tool_results.extend(retry_results)
                    effective_results = retry_results
                    evidence = build_evidence_packet(request.message, effective_results)
            run.evidence = evidence
            verify_evidence_packet(evidence, effective_results, access_context)
            if plan.expected_evidence and not evidence.evidence_ids():
                raise ValueError("task plan expected evidence was not produced")

            self._event(run, "SYNTHESIZE", "从 EvidencePacket 生成业务回答")
            model_answer = operation.answer_policy in {"llm_synthesis", "llm_general"}
            context["synthesis_prompt"] = (
                prompts.GENERAL_SYNTHESIZE
                if operation.answer_policy == "llm_general"
                else prompts.SYNTHESIZE
            )
            synthesis_provider: LLMProvider
            if not model_answer:
                response = _deterministic_response(operation.operation, evidence)
                self._event(run, "DETERMINISTIC_RENDER", "按 answer_policy 零模型渲染")
            elif isinstance(self.provider, FakeProvider):
                synthesis_provider = self.provider
                response = synthesis_provider.synthesize_from_evidence(
                    request.message,
                    evidence,
                    context=context,
                )
            else:
                endpoint_identity = provider_endpoint_identity(self.provider)
                synthesis_context = _synthesis_outbound_context(request.message, evidence, context)
                synthesis_prompt = context["synthesis_prompt"]
                allowed = _may_send_evidence(
                    access_context,
                    self.data_service.data_scope,
                    self.provider,
                    endpoint_identity,
                )
                call_index = self._start_model_egress(
                    run,
                    access_context,
                    purpose="synthesis",
                    prompt=synthesis_prompt,
                    outbound_context=synthesis_context,
                    schema=AssistantResponse,
                    endpoint_identity=endpoint_identity,
                    allowed=allowed,
                )
                if allowed:
                    synthesis_provider = self.provider
                    provider_calls += 1
                    try:
                        response = synthesis_provider.generate_structured(
                            synthesis_prompt,
                            AssistantResponse,
                            context=synthesis_context,
                        )
                    except Exception:
                        self._finish_model_egress(run, access_context, call_index, "failed")
                        raise
                    self._finish_model_egress(run, access_context, call_index, "succeeded")
                else:
                    synthesis_provider = FakeProvider()
                    response = synthesis_provider.synthesize_from_evidence(
                        request.message,
                        evidence,
                        context=context,
                    )
                    self._event(
                        run,
                        "MODEL_EGRESS_DENIED",
                        "证据未发送给模型，改用确定性渲染器",
                    )
            run.response = response
            self._event(run, "VERIFY", "核对证据引用、数字和失败步骤")
            run.verification = verify_response(
                response,
                evidence,
                allow_general_knowledge=operation.answer_policy == "llm_general",
            )
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
            self.trace_store.save_session(session, access_context)
            self.trace_store.save_run(run, access_context)
            return run.model_dump(mode="json")
        except (PermissionError, ValueError, TypeError, RuntimeError) as exc:
            run.status = "failed"
            run.failure_category = run.failure_category or _failure_category(exc)
            run.model_runtime = _provider_runtime(
                self.provider,
                provider_calls=provider_calls,
                usage_offset=usage_offset,
            )
            self._event(run, "FAILED", _safe_failure(exc))
            self.trace_store.save_run(run, access_context)
            raise

    def _execute_plan(
        self, plan: TaskPlan, run: RunRecord, access_context: AccessContext
    ) -> list[ToolResult]:
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
                        access_context,
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
        replanned = FakeProvider().generate_tool_calls(
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
            and any(
                result.step_id == step.step_id and result.status == "failed" for result in results
            )
        }
        accepted_keys: list[tuple[str, str]] = []
        for step in replanned.steps:
            key = (step.tool, _canonical(step.arguments))
            if step.depends_on or key not in failed_root_steps or key in accepted_keys:
                continue
            accepted_keys.append(key)
        if not accepted_keys:
            return None
        id_map = {
            step.step_id: f"s{100 + index}" for index, step in enumerate(original.steps, start=1)
        }
        normalized = [
            step.model_copy(
                update={
                    "step_id": id_map[step.step_id],
                    "depends_on": [id_map[item] for item in step.depends_on],
                }
            )
            for step in original.steps
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

    def _require_production_gate(self) -> None:
        if self.data_service.data_scope != "synthetic" and not self.production_enabled:
            raise PermissionError(
                "production-shadow assistant is disabled until offline validation is promoted"
            )

    def _start_model_egress(
        self,
        run: RunRecord,
        access_context: AccessContext,
        *,
        purpose: str,
        prompt: str,
        outbound_context: dict[str, Any],
        schema: type,
        endpoint_identity: dict[str, str],
        allowed: bool,
    ) -> int:
        payload = {
            "prompt": prompt,
            "context": outbound_context,
            "response_schema": schema.model_json_schema(),
        }
        now = datetime.now(UTC).isoformat()
        run.model_egress.append(
            ModelEgressRecord(
                call_id=f"model-call-{uuid.uuid4().hex}",
                purpose=purpose,
                decision="approved" if allowed else "denied",
                endpoint_policy_id=access_context.model_endpoint_policy_id,
                provider=endpoint_identity["provider"],
                model=endpoint_identity.get("model") or None,
                endpoint_target_hash=endpoint_identity["target_hash"],
                endpoint_binding_verified=AuthorizationService.endpoint_matches(
                    access_context, endpoint_identity
                ),
                exact_payload_hash=_hash_payload(payload),
                outbound_field_paths=_field_paths(payload),
                started_at=now,
                completed_at=None if allowed else now,
                status="started" if allowed else "not_called",
            )
        )
        self.trace_store.save_run(run, access_context)
        return len(run.model_egress) - 1

    def _finish_model_egress(
        self,
        run: RunRecord,
        access_context: AccessContext,
        index: int,
        status: str,
    ) -> None:
        run.model_egress[index] = run.model_egress[index].model_copy(
            update={
                "status": status,
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        self.trace_store.save_run(run, access_context)

    @staticmethod
    def _event(run: RunRecord, state: str, detail: str) -> None:
        from datetime import UTC, datetime

        run.events.append(
            {"state": state, "detail": detail, "timestamp": datetime.now(UTC).isoformat()}
        )


def _readiness_capability_match(
    registry: CapabilityRegistry, data_scope: str, available_tools: set[str]
) -> CapabilityMatch:
    definition = next(
        (
            item
            for item in registry.definitions
            if item.id == "production_capability_readiness" and data_scope in item.data_scopes
        ),
        None,
    )
    if definition is None:
        raise ValueError("capability readiness fallback is not registered for this data scope")
    unavailable = sorted(set(definition.tools) - available_tools)
    if unavailable:
        raise ValueError("capability readiness tools are not available")
    return CapabilityMatch(
        status="matched",
        capability_id=definition.id,
        registry_version=registry.registry_version,
        tools=definition.tools,
        answer_policy=definition.answer_policy,
        completeness_policy=definition.completeness_policy,
    )


def _verify_plan_capability(plan: TaskPlan, match: CapabilityMatch | None) -> None:
    if match is None or match.status != "matched":
        raise ValueError("task has no matched runtime capability")
    outside = sorted({step.tool for step in plan.steps} - set(match.tools))
    if outside:
        raise ValueError(f"task plan escaped its registered capability: {', '.join(outside)}")


def _deterministic_response(operation: str, evidence: EvidencePacket) -> AssistantResponse:
    items = [
        item
        for group in (
            evidence.facts,
            evidence.statistics,
            evidence.charts,
            evidence.model_outputs,
            evidence.knowledge_sources,
        )
        for item in group
    ]
    claims = [item.claim for item in items]
    details: list[str] = []
    if operation == "list_metrics":
        rows = [
            row
            for item in items
            for row in (item.value.get("rows", []) if isinstance(item.value, dict) else [])
        ]
        details = [
            str(row.get("name") or row.get("label") or row.get("id"))
            + (f"（{row['id']}）" if row.get("id") else "")
            for row in rows
        ]
    elif operation == "list_available_dates":
        rows = [
            row
            for item in items
            for row in (item.value.get("rows", []) if isinstance(item.value, dict) else [])
        ]
        details = [str(row["date"]) for row in rows if row.get("date")]
    elif operation == "capability_help":
        rows = [
            row
            for item in items
            for row in (item.value.get("rows", []) if isinstance(item.value, dict) else [])
        ]
        details = [
            f"{row.get('label')}（{row.get('operations')}）"
            for row in rows
            if row.get("label") and row.get("operations")
        ]
    readiness_actions = [
        str(row.get("action") or row.get("requirement"))
        for item in items
        if item.coverage.coverage_type == "capability_readiness"
        for row in (item.value.get("rows", []) if isinstance(item.value, dict) else [])
        if row.get("action") or row.get("requirement")
    ]
    answer_parts = claims or ["当前工具未返回足够证据。"]
    if details:
        answer_parts.append("、".join(details))
    if readiness_actions:
        answer_parts.append("待补齐：" + "；".join(readiness_actions))
    recommendations: list[str] = []
    assumptions: list[str] = []
    if operation == "travel_plan":
        for item in items:
            value = item.value if isinstance(item.value, dict) else {}
            summary = value.get("summary", {}) if isinstance(value, dict) else {}
            if isinstance(summary, dict):
                recommendations.extend(str(value) for value in summary.get("recommendations", []))
                assumptions.extend(str(value) for value in summary.get("assumptions", []))
    return AssistantResponse(
        answer="；".join(answer_parts),
        key_findings=claims,
        evidence_refs=[item.evidence_id for item in items],
        recommendations=recommendations,
        assumptions=assumptions,
        limitations=[*evidence.missing_evidence, *evidence.conflicts],
    )


def _capability_readiness_plan(intent: IntentEnvelope) -> TaskPlan:
    return TaskPlan(
        plan_id=f"plan-{intent.task_type}-capability-readiness",
        task_type=intent.task_type,
        steps=[
            ToolStep(
                step_id="s1",
                tool="get_data_quality_status",
                arguments={},
            ),
            ToolStep(
                step_id="s2",
                tool="assess_task_readiness",
                arguments={"task_type": intent.task_type},
                depends_on=["s1"],
            ),
        ],
        expected_evidence=["capability admission requirements"],
        answer_format="capability_readiness",
    )


def _lock_protected_intent(candidate: IntentEnvelope, protected: IntentEnvelope) -> IntentEnvelope:
    """Model may improve semantics, but server-owned routing fields are immutable."""

    return candidate.model_copy(
        update={
            "metric_version": protected.metric_version,
            "city": protected.city,
            "dataset_role": protected.dataset_role,
            "source_version": protected.source_version,
            "time_grain": protected.time_grain,
        }
    )


def _apply_relative_period_availability_gate(
    intent: IntentEnvelope, question: str, catalog: dict[str, Any]
) -> IntentEnvelope:
    if not any(token in question for token in ("环比", "同比", "上期")):
        return intent
    resolved = intent.time_scope.get("resolved_range")
    available = catalog.get("default_time_range")
    if not isinstance(resolved, dict) or not isinstance(available, dict):
        return intent
    start = _parse_datetime(resolved.get("start"))
    end = _parse_datetime(resolved.get("end"))
    available_start = _parse_datetime(available.get("start"))
    available_end = _parse_datetime(available.get("end"))
    if None in {start, end, available_start, available_end}:
        return intent
    assert start is not None and end is not None
    assert available_start is not None and available_end is not None
    if "同比" in question:
        try:
            baseline_start = start.replace(year=start.year - 1)
            baseline_end = end.replace(year=end.year - 1)
        except ValueError:
            baseline_start = start - timedelta(days=365)
            baseline_end = end - timedelta(days=365)
    else:
        duration = end - start
        baseline_start, baseline_end = start - duration, start
    if baseline_start >= available_start and baseline_end <= available_end:
        return intent
    message = "当前受控数据范围不包含完整基期，不能执行同比、环比或上期比较。"
    return intent.model_copy(
        update={
            "needs_clarification": True,
            "ambiguities": [*intent.ambiguities, message],
        }
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _may_call_model(
    context: AccessContext,
    data_scope: str,
    provider: LLMProvider,
    endpoint_identity: dict[str, str],
) -> bool:
    return not isinstance(provider, FakeProvider) and AuthorizationService.may_send_intent_to_model(
        context, data_scope, endpoint_identity
    )


def _may_send_evidence(
    context: AccessContext,
    data_scope: str,
    provider: LLMProvider,
    endpoint_identity: dict[str, str],
) -> bool:
    return not isinstance(
        provider, FakeProvider
    ) and AuthorizationService.may_send_evidence_to_model(context, data_scope, endpoint_identity)


def _intent_outbound_context(
    context: dict[str, Any], protected_intent: IntentEnvelope
) -> dict[str, Any]:
    catalog = context["catalog"]
    return {
        "data_scope": context["data_scope"],
        "question": context["question"],
        "recent_history": context.get("recent_history", [])[-6:],
        "catalog": {
            "city": catalog.get("city"),
            "source_version": catalog.get("source_version"),
            "default_time_range": catalog.get("default_time_range"),
            "metrics": [
                {
                    "id": item.get("id"),
                    "version": item.get("version"),
                    "dimensions": item.get("dimensions", []),
                }
                for item in catalog.get("metrics", [])
            ],
            "lines": catalog.get("lines", []),
            "stations": catalog.get("stations", []),
            "directions": catalog.get("directions", []),
        },
        "candidate_domain": {
            "task_types": [
                "query",
                "compare",
                "forecast",
                "alert",
                "transfer",
                "geo",
                "correlation",
                "diagnosis",
                "trend",
                "report",
                "travel",
                "help",
                "general",
            ],
            "allowed_metrics": [item.get("id") for item in catalog.get("metrics", [])],
        },
        "immutable_scope": {
            "metric_version": protected_intent.metric_version,
            "city": protected_intent.city,
            "dataset_role": protected_intent.dataset_role,
            "source_version": protected_intent.source_version,
            "time_grain": protected_intent.time_grain,
        },
    }


def _synthesis_outbound_context(
    question: str, evidence: EvidencePacket, context: dict[str, Any]
) -> dict[str, Any]:
    return {
        "data_scope": context["data_scope"],
        "question": question,
        "task_type": context.get("intent", {}).get("task_type"),
        "evidence": evidence.model_dump(mode="json"),
    }


def _hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _field_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths = [
            path
            for key in sorted(value)
            for path in _field_paths(value[key], f"{prefix}.{key}" if prefix else key)
        ]
        return paths or ([prefix] if prefix else [])
    if isinstance(value, list):
        paths = [
            path
            for index, item in enumerate(value)
            for path in _field_paths(item, f"{prefix}[{index}]")
        ]
        return paths or ([prefix] if prefix else [])
    return [prefix]


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


def _failure_category(exc: Exception) -> str:
    message = str(exc).lower()
    if isinstance(exc, PermissionError):
        return "authorization_failure"
    if isinstance(exc, RuntimeError):
        return "model_failure"
    if "entity" in message and ("not observed" in message or "outside" in message):
        return "entity_not_found"
    if "capability" in message or "unregistered tool" in message:
        return "capability_gap"
    if "query" in message and ("unsupported" in message or "invalid" in message):
        return "query_ir_unsupported"
    if "truncat" in message or "incomplete" in message:
        return "result_truncated"
    if "evidence" in message or "verification" in message or "response failed" in message:
        return "verification_failure"
    if "tool" in message:
        return "tool_failure"
    return "data_unavailable"
