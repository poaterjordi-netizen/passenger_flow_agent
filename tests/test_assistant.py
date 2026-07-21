import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest.mock import patch

from metro_agent.access import AccessContext
from metro_agent.api.models import QueryRequest
from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import (
    AssistantService,
    _provider_runtime,
    provider_from_environment,
)
from metro_agent.assistant.provider import (
    FakeProvider,
    HermesCodexProvider,
    OpenAICompatibleProvider,
)
from metro_agent.assistant.dataset_export import DATASET_FILES, export_verified_trajectories
from metro_agent.assistant.evidence import build_evidence_packet
from metro_agent.assistant.failure_analysis import summarize_failure_traces
from metro_agent.assistant.schemas import (
    AssistantMessageRequest,
    AssistantResponse,
    EvidenceItem,
    EvidencePacket,
    HumanFeedbackRequest,
    IntentEnvelope,
    StructuredClaim,
    TaskPlan,
    ToolResult,
)
from metro_agent.assistant.tool_registry import ToolRegistry
from metro_agent.assistant.verifier import verify_evidence_packet, verify_response
from scripts.evaluate_gpt56_shadow import _checks as shadow_checks

ROOT = Path(__file__).resolve().parents[1]


class AssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.root = root
        service = SyntheticApiService(
            ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=root / "audits",
                environment="test",
            )
        )
        self.service = service
        self.assistant = AssistantService(service, root / "assistant", provider=FakeProvider())

    def test_operation_ir_discovery_variants_use_zero_model_calls(self) -> None:
        class CountingProvider(FakeProvider):
            def __init__(self) -> None:
                self.synthesis_calls = 0

            def synthesize_from_evidence(self, question, evidence, *, context):
                self.synthesis_calls += 1
                return super().synthesize_from_evidence(question, evidence, context=context)

        provider = CountingProvider()
        assistant = AssistantService(
            self.service,
            self.root / "operation-discovery",
            provider=provider,
        )
        cases = {
            "有哪些车站": ("list_entities", "entity_inventory"),
            "车站清单": ("list_entities", "entity_inventory"),
            "把数据库里的地铁站给我": ("list_entities", "entity_inventory"),
            "有哪些指标": ("list_metrics", "metric_catalog"),
            "数据覆盖哪些日期": ("list_available_dates", "date_catalog"),
            "数据库基本情况": ("summarize_dataset", "data_scope_summary"),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                session_id = assistant.create_session()["session_id"]
                run = assistant.message(session_id, AssistantMessageRequest(message=question))
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["operation_ir"]["operation"], expected[0])
                self.assertEqual(run["capability_match"]["capability_id"], expected[1])
                self.assertEqual(run["model_runtime"]["model_calls"], 0)
                self.assertEqual(run["model_runtime"]["provider_calls"], 0)
                self.assertEqual(
                    run["operation_ir"]["answer_policy"].split("_")[0], "deterministic"
                )
                coverage = run["tool_results"][0]["coverage"]
                self.assertTrue(coverage["complete"])
                self.assertFalse(coverage["truncated"])
                self.assertEqual(
                    coverage["returned_count"], run["tool_results"][0]["returned_row_count"]
                )
        self.assertEqual(provider.synthesis_calls, 0)

    def test_failed_trace_clustering_yields_regression_candidate(self) -> None:
        session_id = self.assistant.create_session()["session_id"]
        run = self.assistant.message(session_id, AssistantMessageRequest(message="帮我看看"))
        self.assertEqual(run["status"], "needs_clarification")
        report = summarize_failure_traces(self.root / "assistant" / "traces")
        self.assertEqual(report["failed_or_clarified_run_count"], 1)
        self.assertEqual(report["clusters"][0]["failure_category"], "material_ambiguity")
        self.assertEqual(report["clusters"][0]["regression_candidate"]["question"], "帮我看看")

    def test_travel_planning_is_deterministic_and_only_requires_endpoints(self) -> None:
        cases = (
            "我要从北京交通大学到北京工业大学，给出合理的出现规划",
            "从北交大到北工大怎么走",
            "从北京交通大学到北京工业大学出行规划",
        )
        for question in cases:
            with self.subTest(question=question):
                session_id = self.assistant.create_session()["session_id"]
                run = self.assistant.message(session_id, AssistantMessageRequest(message=question))
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["intent"]["task_type"], "travel")
                self.assertEqual(run["intent_route"], "deterministic")
                self.assertEqual(run["operation_ir"]["operation"], "travel_plan")
                self.assertEqual(run["capability_match"]["capability_id"], "travel_planning")
                self.assertEqual(run["plan"]["steps"][0]["tool"], "plan_public_transit_route")
                self.assertEqual(run["model_runtime"]["model_calls"], 0)
                self.assertEqual(run["model_runtime"]["provider_calls"], 0)
                self.assertTrue(run["verification"]["valid"])
                self.assertIn("西直门", run["response"]["answer"])
                self.assertIn("北工大西门", run["response"]["answer"])
                result = run["tool_results"][0]
                self.assertEqual(result["coverage"]["coverage_type"], "external_navigation")
                self.assertTrue(result["coverage"]["complete"])
                navigation = result["summary"]["navigation_links"]
                self.assertTrue(navigation[0]["url"].startswith("https://api.map.baidu.com/"))

        session_id = self.assistant.create_session()["session_id"]
        generic = self.assistant.message(
            session_id, AssistantMessageRequest(message="从天安门到颐和园怎么走")
        )
        self.assertEqual(generic["status"], "completed")
        self.assertIn("实时地图导航入口", generic["response"]["answer"])
        self.assertNotIn("西直门", generic["response"]["answer"])

        session_id = self.assistant.create_session()["session_id"]
        missing = self.assistant.message(
            session_id, AssistantMessageRequest(message="从北京交通大学出发怎么走")
        )
        self.assertEqual(missing["status"], "needs_clarification")
        self.assertEqual(missing["capability_match"]["missing_slots"], ["destination"])
        self.assertEqual(
            missing["response"]["follow_up_questions"], ["任务缺少会改变执行结果的必要字段：终点。"]
        )
        self.assertFalse(missing["tool_results"])

    def test_capability_help_and_general_fallback_cover_open_questions(self) -> None:
        session_id = self.assistant.create_session()["session_id"]
        help_run = self.assistant.message(
            session_id, AssistantMessageRequest(message="你能做什么？")
        )
        self.assertEqual(help_run["status"], "completed")
        self.assertEqual(help_run["intent"]["task_type"], "help")
        self.assertEqual(help_run["operation_ir"]["operation"], "capability_help")
        self.assertEqual(
            help_run["capability_match"]["capability_id"],
            "assistant_capability_help",
        )
        self.assertEqual(help_run["model_runtime"]["provider_calls"], 0)
        self.assertIn("GPT 通用问答", help_run["response"]["answer"])

        class GeneralProvider:
            name = "general-provider"
            model = "general-model"

            def __init__(self):
                self.usage_records = []

            def generate_structured(self, prompt, schema, *, context):
                self.usage_records.append(
                    {
                        "api_calls": 1,
                        "completed": True,
                        "failed": False,
                        "input_tokens": 20,
                        "output_tokens": 20,
                        "total_tokens": 40,
                    }
                )
                return schema.model_validate(
                    {
                        "answer": "断面客流用于描述列车或线路通过某一断面的客流规模。",
                        "key_findings": ["这是通用概念说明，不是数据库查询结果。"],
                        "evidence_refs": ["ev-s1"],
                        "limitations": ["未读取 metroflow 数据库业务行。"],
                    }
                )

            def generate_tool_calls(self, prompt, *, context):
                raise AssertionError("planner must remain deterministic")

            def synthesize_from_evidence(self, question, evidence, *, context):
                raise AssertionError("structured synthesis path should be used")

            def stream_text(self, prompt, *, context):
                return iter(())

        assistant = AssistantService(
            self.service,
            self.root / "general-answer",
            provider=GeneralProvider(),
        )
        session_id = assistant.create_session()["session_id"]
        general = assistant.message(
            session_id, AssistantMessageRequest(message="什么是地铁断面客流？")
        )
        self.assertEqual(general["status"], "completed")
        self.assertEqual(general["intent_route"], "deterministic")
        self.assertEqual(general["intent"]["task_type"], "general")
        self.assertEqual(general["operation_ir"]["operation"], "general_answer")
        self.assertEqual(general["operation_ir"]["answer_policy"], "llm_general")
        self.assertEqual(
            general["capability_match"]["capability_id"],
            "general_question_answering",
        )
        self.assertEqual(
            [item["tool"] for item in general["tool_results"]],
            ["prepare_general_context"],
        )
        self.assertFalse(general["tool_results"][0]["rows"][0]["database_rows_included"])
        self.assertEqual(general["model_runtime"]["provider_calls"], 1)
        self.assertEqual(general["model_runtime"]["model_calls"], 1)
        self.assertTrue(general["verification"]["valid"])
        self.assertIn("general knowledge", general["verification"]["warnings"][0])

        for question in ("比较北京和上海哪个更适合旅游？", "预测明天北京天气"):
            with self.subTest(question=question):
                parsed = FakeProvider().generate_structured(
                    "",
                    IntentEnvelope,
                    context=self.assistant.context_builder.build(question, []),
                )
                self.assertEqual(parsed.task_type, "general")

        business = FakeProvider().generate_structured(
            "",
            IntentEnvelope,
            context=self.assistant.context_builder.build("比较两个时段进站客流", []),
        )
        self.assertEqual(business.task_type, "compare")

    def test_ten_task_types_complete_with_verified_evidence(self) -> None:
        questions = {
            "query": "查询各站进站客流",
            "compare": "比较两个时段进站客流",
            "forecast": "奥体中心4万人演唱会预测",
            "alert": "实时站台密度预警",
            "transfer": "统计30分钟公交轨道换乘量",
            "geo": "绘制通勤热力图",
            "correlation": "分析客流与正点率相关性",
            "diagnosis": "昨天客流为什么下降",
            "trend": "分析中长期趋势",
            "report": "生成日报",
        }
        session = self.assistant.create_session()["session_id"]
        for expected, question in questions.items():
            with self.subTest(task_type=expected):
                run = self.assistant.message(session, AssistantMessageRequest(message=question))
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["intent"]["task_type"], expected)
                self.assertTrue(run["verification"]["valid"])
                self.assertTrue(run["response"]["evidence_refs"])
                self.assertEqual(self.assistant.get_run(run["run_id"])["run_id"], run["run_id"])
                self.assertEqual(self.assistant.get_events(run["run_id"])[-1]["state"], "RESPOND")

    def test_provider_contract_supports_structured_plan_and_streaming(self) -> None:
        provider = FakeProvider()
        context = self.assistant.context_builder.build("查询进站客流", [])
        intent = provider.generate_structured(
            "",
            __import__("metro_agent.assistant.schemas", fromlist=["IntentEnvelope"]).IntentEnvelope,
            context=context,
        )
        context["intent"] = intent.model_dump(mode="json")
        plan = provider.generate_structured("", TaskPlan, context=context)
        self.assertEqual(plan.steps[0].tool, "query_metric")
        self.assertEqual(
            "".join(provider.stream_text("", context=context)), "正在理解、规划、执行工具、核验证据"
        )

    def test_openai_adapter_parses_streaming_sse_without_network(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def __iter__(self):
                return iter(
                    [
                        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
                        b'data: {"choices":[{"delta":{"content":" world"}}]}\n',
                        b"data: [DONE]\n",
                    ]
                )

        provider = OpenAICompatibleProvider(api_key="test-only", base_url="https://example.test/v1")
        with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            self.assertEqual("".join(provider.stream_text("prompt", context={})), "hello world")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")

    def test_hermes_codex_adapter_uses_safe_oauth_bridge_and_validates_json(self) -> None:
        def completed(command, **kwargs):
            usage_path = Path(command[command.index("--usage-file") + 1])
            usage_path.write_text(
                json.dumps(
                    {
                        "model": "gpt-5.6-sol",
                        "provider": "openai-codex",
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "api_calls": 1,
                        "completed": True,
                        "failed": False,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "task_type": "query",
                        "user_goal": "查询进站客流",
                        "entities": {},
                        "metrics": ["entries"],
                        "time_scope": {},
                        "ambiguities": [],
                        "needs_clarification": False,
                        "event_spec": None,
                        "transfer_spec": None,
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        provider = HermesCodexProvider(command="/opt/hermes", model="gpt-5.6-sol")
        context = self.assistant.context_builder.build("查询进站客流", [])
        with patch("subprocess.run", side_effect=completed) as run:
            intent = provider.generate_structured("planner", IntentEnvelope, context=context)
        command = run.call_args.args[0]
        prompt = command[command.index("-z") + 1]
        self.assertEqual(intent.task_type, "query")
        self.assertIn("--safe-mode", command)
        self.assertNotIn("Return that exact intent", prompt)
        self.assertNotIn("protected_reference_intent", prompt)
        self.assertEqual(command[command.index("--provider") + 1], "openai-codex")
        self.assertEqual(command[command.index("-m") + 1], "gpt-5.6-sol")
        self.assertEqual(provider.usage_records[0]["provider"], "openai-codex")

    def test_provider_environment_selects_hermes_codex_without_copying_credentials(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "METRO_ASSISTANT_PROVIDER": "hermes-codex",
                "METRO_ASSISTANT_MODEL": "gpt-5.6-sol",
                "METRO_ASSISTANT_HERMES_COMMAND": "/opt/hermes",
            },
            clear=False,
        ):
            provider = provider_from_environment()
        self.assertIsInstance(provider, HermesCodexProvider)
        self.assertEqual(provider.model, "gpt-5.6-sol")

    def test_hermes_runtime_metadata_aggregates_safe_per_run_usage(self) -> None:
        provider = HermesCodexProvider(command="/opt/hermes", model="gpt-5.6-sol")
        provider.usage_records.extend(
            [
                {
                    "api_calls": 1,
                    "completed": True,
                    "failed": False,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "reasoning_tokens": 3,
                    "total_tokens": 123,
                    "elapsed_seconds": 1.25,
                },
                {
                    "api_calls": 1,
                    "completed": True,
                    "failed": False,
                    "input_tokens": 200,
                    "output_tokens": 30,
                    "reasoning_tokens": 4,
                    "total_tokens": 234,
                    "elapsed_seconds": 2.5,
                },
            ]
        )
        runtime = _provider_runtime(provider, provider_calls=2)
        self.assertEqual(runtime.mode, "local_governed_model")
        self.assertEqual(runtime.execution_role, "model_active")
        self.assertTrue(runtime.real_model_active)
        self.assertTrue(runtime.real_model_configured)
        self.assertEqual(runtime.invocation_status, "succeeded")
        self.assertEqual(runtime.usage_reporting, "complete")
        self.assertEqual(runtime.model_calls, 2)
        self.assertEqual(runtime.input_tokens, 300)
        self.assertEqual(runtime.total_tokens, 357)
        self.assertEqual(runtime.elapsed_seconds, 3.75)

    def test_openai_adapter_records_actual_usage_and_model_identity(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "task_type": "query",
                                            "user_goal": "查询进站客流",
                                            "entities": {},
                                            "metrics": ["entries"],
                                            "time_scope": {},
                                            "ambiguities": [],
                                            "needs_clarification": False,
                                            "event_spec": None,
                                            "transfer_spec": None,
                                        }
                                    )
                                }
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 101,
                            "completion_tokens": 22,
                            "total_tokens": 123,
                            "completion_tokens_details": {"reasoning_tokens": 7},
                        },
                    }
                ).encode()

        provider = OpenAICompatibleProvider(
            api_key="test-only",
            base_url="https://example.test/v1",
            model="test-model",
        )
        with patch("urllib.request.urlopen", return_value=Response()):
            provider.generate_structured("planner", IntentEnvelope, context={})
        runtime = _provider_runtime(provider, provider_calls=1)
        self.assertEqual(runtime.provider, "openai-compatible:test-model")
        self.assertEqual(runtime.model, "test-model")
        self.assertEqual(runtime.model_calls, 1)
        self.assertEqual(runtime.input_tokens, 101)
        self.assertEqual(runtime.reasoning_tokens, 7)
        self.assertEqual(runtime.total_tokens, 123)
        self.assertEqual(runtime.invocation_status, "succeeded")
        self.assertEqual(runtime.usage_reporting, "complete")

    def test_openai_adapter_records_failed_call_without_fabricating_tokens(self) -> None:
        provider = OpenAICompatibleProvider(
            api_key="test-only",
            base_url="https://example.test/v1",
        )
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "language model request failed"):
                provider.generate_structured("planner", IntentEnvelope, context={})
        runtime = _provider_runtime(provider, provider_calls=1)
        self.assertEqual(runtime.model_calls, 1)
        self.assertEqual(runtime.invocation_status, "failed")
        self.assertEqual(runtime.usage_reporting, "unavailable")
        self.assertIsNone(runtime.total_tokens)

    def test_openai_adapter_marks_invalid_structured_output_as_failed(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "not-json"}}],
                        "usage": {
                            "prompt_tokens": 4,
                            "completion_tokens": 1,
                            "total_tokens": 5,
                        },
                    }
                ).encode()

        provider = OpenAICompatibleProvider(api_key="test-only")
        with patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "invalid structured output"):
                provider.generate_structured("planner", IntentEnvelope, context={})
        runtime = _provider_runtime(provider, provider_calls=1)
        self.assertEqual(runtime.model_calls, 1)
        self.assertEqual(runtime.invocation_status, "failed")
        self.assertEqual(runtime.total_tokens, 5)

    def test_hermes_bridge_failure_is_counted_without_exposing_subprocess_details(self) -> None:
        provider = HermesCodexProvider(command="/missing/hermes", model="gpt-5.6-sol")
        with patch("subprocess.run", side_effect=FileNotFoundError("secret path")):
            with self.assertRaisesRegex(RuntimeError, "bridge invocation failed"):
                provider._invoke("planner")
        runtime = _provider_runtime(provider, provider_calls=1)
        self.assertEqual(runtime.model_calls, 1)
        self.assertEqual(runtime.invocation_status, "failed")
        self.assertIsNone(runtime.total_tokens)

    def test_hermes_codex_plan_is_bounded_by_deterministic_reference(self) -> None:
        context = self.assistant.context_builder.build("查询各站进站客流", [])
        intent = FakeProvider().generate_structured("", IntentEnvelope, context=context)
        context["intent"] = intent.model_dump(mode="json")
        expected = FakeProvider().generate_tool_calls("", context=context)
        provider = HermesCodexProvider(command="/opt/hermes", model="gpt-5.6-sol")
        with patch.object(provider, "_invoke", return_value=expected.model_dump_json()) as invoke:
            actual = provider.generate_tool_calls("planner", context=context)
        self.assertEqual(actual, expected)
        self.assertIn("protected_reference_plan", invoke.call_args.args[0])

    def test_plan_rejects_forward_dependencies_and_unknown_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "forward dependencies"):
            TaskPlan.model_validate(
                {
                    "plan_id": "bad",
                    "task_type": "query",
                    "steps": [
                        {
                            "step_id": "s1",
                            "tool": "query_metric",
                            "arguments": {},
                            "depends_on": ["s2"],
                        },
                        {
                            "step_id": "s2",
                            "tool": "query_metric",
                            "arguments": {},
                            "depends_on": [],
                        },
                    ],
                    "expected_evidence": [],
                }
            )
        report = verify_response(
            AssistantResponse(answer="x", evidence_refs=["ev-missing"]),
            EvidencePacket(question="q"),
        )
        self.assertFalse(report.valid)

    def test_evidence_hash_lineage_scope_and_completeness_are_verified(self) -> None:
        context = AccessContext.synthetic_local()
        request = QueryRequest.model_validate(
            {
                "metric": "entries",
                "time_range": {
                    "start": "2026-07-20T08:00:00+08:00",
                    "end": "2026-07-20T10:00:00+08:00",
                },
                "dimensions": ["station"],
                "filters": [],
                "limit": 10,
            }
        )
        result = self.assistant.tools.execute(
            "s1", "query_metric", request.model_dump(mode="json"), [], context
        )
        packet = build_evidence_packet("query", [result])
        verify_evidence_packet(packet, [result], context)

        packet.facts[0].result_hash = "0" * 64
        with self.assertRaisesRegex(ValueError, "result hash"):
            verify_evidence_packet(packet, [result], context)

        incomplete = EvidencePacket(
            question="q",
            facts=[
                EvidenceItem(
                    evidence_id="ev-incomplete",
                    step_id="s1",
                    kind="fact",
                    claim="partial",
                    complete=False,
                    truncated=True,
                )
            ],
        )
        report = verify_response(
            AssistantResponse(answer="partial", evidence_refs=["ev-incomplete"]),
            incomplete,
        )
        self.assertFalse(report.valid)
        self.assertIn("cited evidence is incomplete: ev-incomplete", report.errors)

    def test_high_confidence_deterministic_route_does_not_call_model_intent(self) -> None:
        class DriftedIntentProvider(FakeProvider):
            def generate_structured(self, prompt, schema, *, context):
                result = super().generate_structured(prompt, schema, context=context)
                if schema is IntentEnvelope:
                    return result.model_copy(update={"metrics": ["exits"]})
                return result

        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "intent-drift-assistant",
            provider=DriftedIntentProvider(),
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="查询各站进站客流"))
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["intent_route"], "deterministic")
        self.assertEqual(run["intent"]["metrics"], ["entries"])

    def test_abstain_model_intent_call_is_minimal_and_audited_before_clarification(self) -> None:
        class CandidateProvider:
            name = "candidate-provider"
            model = "candidate-model"

            def generate_structured(self, prompt, schema, *, context):
                candidate = FakeProvider().generate_structured(prompt, schema, context=context)
                return candidate.model_copy(
                    update={
                        "needs_clarification": True,
                        "ambiguities": ["需要明确业务问题"],
                    }
                )

            def generate_tool_calls(self, prompt, *, context):
                raise AssertionError("planner must remain deterministic")

            def synthesize_from_evidence(self, question, evidence, *, context):
                raise AssertionError("clarification must stop before synthesis")

            def stream_text(self, prompt, *, context):
                return iter(())

        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "intent-egress-assistant",
            provider=CandidateProvider(),
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="概览"))

        self.assertEqual(run["status"], "needs_clarification")
        self.assertEqual(run["intent_route"], "model_candidate")
        self.assertEqual(len(run["model_egress"]), 1)
        call = run["model_egress"][0]
        self.assertEqual(call["purpose"], "intent_candidate")
        self.assertEqual(call["decision"], "approved")
        self.assertEqual(call["status"], "succeeded")
        self.assertTrue(call["exact_payload_hash"])
        paths = set(call["outbound_field_paths"])
        self.assertIn("context.question", paths)
        self.assertFalse(any("authorization" in item for item in paths))
        self.assertFalse(any("business_dictionary" in item for item in paths))
        self.assertFalse(any("available_tools" in item for item in paths))

    def test_failed_intent_model_call_remains_in_the_persisted_trace(self) -> None:
        class FailingProvider:
            name = "failing-provider"
            model = "failing-model"

            def generate_structured(self, prompt, schema, *, context):
                raise RuntimeError("simulated provider failure")

            def generate_tool_calls(self, prompt, *, context):
                raise AssertionError("planner must remain deterministic")

            def synthesize_from_evidence(self, question, evidence, *, context):
                raise AssertionError("synthesis must not run")

            def stream_text(self, prompt, *, context):
                return iter(())

        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "failed-egress-assistant",
            provider=FailingProvider(),
        )
        session = assistant.create_session()["session_id"]
        with self.assertRaisesRegex(RuntimeError, "simulated provider failure"):
            assistant.message(session, AssistantMessageRequest(message="概览"))

        run_paths = list(assistant.trace_store.runs.glob("run-*.json"))
        self.assertEqual(len(run_paths), 1)
        persisted = json.loads(run_paths[0].read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted["model_egress"][0]["purpose"], "intent_candidate")
        self.assertEqual(persisted["model_egress"][0]["status"], "failed")
        self.assertIsNotNone(persisted["model_egress"][0]["completed_at"])

    def test_model_cannot_change_deterministic_plan_arguments(self) -> None:
        class DriftedPlanProvider(FakeProvider):
            def generate_tool_calls(self, prompt, *, context):
                plan = super().generate_tool_calls(prompt, context=context)
                changed = plan.steps[0].model_copy(
                    update={"arguments": {**plan.steps[0].arguments, "limit": 1}}
                )
                return plan.model_copy(update={"steps": [changed, *plan.steps[1:]]})

        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "plan-drift-assistant",
            provider=DriftedPlanProvider(),
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="查询各站进站客流"))
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["planner_route"], "deterministic")
        self.assertEqual(run["plan"]["steps"][0]["arguments"]["limit"], 100)

    def test_tool_registry_covers_statistics_forecast_transfer_geo_and_report(self) -> None:
        registry: ToolRegistry = self.assistant.tools
        required_tools = {
            "get_metric_catalog",
            "query_metric",
            "compare_metric_periods",
            "rank_stations",
            "get_audit_summary",
            "run_reference_day_forecast",
            "find_similar_historical_days",
            "compare_forecast_with_baseline",
            "run_event_forecast",
            "run_station_forecast",
            "run_network_forecast",
            "evaluate_forecast",
            "calculate_growth",
            "calculate_correlation",
            "calculate_lagged_correlation",
            "detect_anomalies",
            "decompose_time_series",
            "compare_groups",
            "rank_contributors",
            "query_rail_transactions",
            "query_bus_transactions",
            "match_transfer_records",
            "calculate_transfer_flow",
            "analyze_transfer_window",
            "compare_transfer_rules",
            "geocode_stations",
            "aggregate_flow_by_region",
            "build_od_heatmap",
            "build_station_heatmap",
            "build_commuting_profile",
            "render_geo_dataset",
            "search_operating_sop",
            "search_event_response_cases",
            "get_station_capacity_rules",
            "get_alert_thresholds",
            "build_action_candidates",
            "build_analysis_report",
            "build_daily_report",
            "build_event_report",
            "build_alert_brief",
            "export_report",
        }
        self.assertTrue(required_tools.issubset(set(registry.names)))
        catalog = self.assistant.data_service.catalog()
        query = QueryRequest.model_validate(
            {
                "metric": "entries",
                "time_range": catalog["default_time_range"],
                "dimensions": ["station"],
                "filters": [],
                "limit": 100,
            }
        )
        result = registry.execute("s1", "query_metric", query.model_dump(mode="json"), [])
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.rows), 2)
        event = registry.execute(
            "s2",
            "run_event_forecast",
            {
                "reference_date": date(2026, 7, 20).isoformat(),
                "target_date": date(2026, 7, 21).isoformat(),
                "attendance": 40_000,
                "impacted_stations": ["S-ALPHA"],
            },
            [],
        )
        self.assertEqual(event.status, "success")
        self.assertIn("尚未经过真实活动回测", event.warnings[0])
        baseline = registry.execute(
            "baseline",
            "run_reference_day_forecast",
            {
                "reference_date": date(2026, 7, 20).isoformat(),
                "target_date": date(2026, 7, 21).isoformat(),
            },
            [],
        )
        beta_baseline = [row for row in baseline.rows if row["station_id"] == "S-BETA"]
        beta_event = [row for row in event.rows if row["station_id"] == "S-BETA"]
        self.assertEqual(beta_event, beta_baseline)
        audit = registry.execute("audit", "get_audit_summary", {}, [result])
        self.assertEqual(audit.status, "success")
        action = registry.execute("action", "build_action_candidates", {"scenario": "crowding"}, [])
        self.assertTrue(action.summary["action_plan"]["requires_human_confirmation"])
        trend = registry.execute(
            "trend", "run_time_series_forecast", {"values": [100, 110, 125], "horizon": 2}, []
        )
        self.assertEqual(trend.status, "success")
        self.assertIn("lower_95", trend.rows[0])
        heatmap = registry.execute("geo", "build_od_heatmap", {}, [])
        geo_payload = json.loads(Path(heatmap.artifact_refs[0]).read_text(encoding="utf-8"))
        self.assertEqual(geo_payload["geojson"]["type"], "FeatureCollection")
        self.assertEqual(geo_payload["geojson"]["features"][0]["geometry"]["type"], "LineString")

    def test_trace_identifiers_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid trace identifier"):
            self.assistant.trace_store.get_run("../secret")

    def test_gold_case_fixture_has_exact_category_counts(self) -> None:
        payload = json.loads(
            (ROOT / "examples/assistant_gold_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["cases"]), 100)
        counts = {}
        for case in payload["cases"]:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        self.assertEqual(counts["scheduled_report"], 5)
        self.assertEqual(counts["geo_heatmap"], 5)
        self.assertEqual(sum(counts.values()), 100)
        self.assertEqual(len({case["question"] for case in payload["cases"]}), 100)
        self.assertFalse(any("第 1 个用例" in case["question"] for case in payload["cases"]))

    def test_query_plan_resolves_metric_filters_dimensions_and_top_n(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(
            session,
            AssistantMessageRequest(message="查询 1 号线上行各站出站客流，按客流排序，只看前三名"),
        )
        self.assertEqual(run["intent"]["metrics"], ["exits"])
        self.assertEqual(run["intent"]["entities"]["lines"], ["L-A"])
        self.assertEqual(run["intent"]["entities"]["directions"], ["up"])
        self.assertEqual(run["plan"]["steps"][0]["arguments"]["dimensions"], ["station"])
        self.assertEqual(
            run["plan"]["steps"][0]["arguments"]["filters"],
            [
                {"field": "line_id", "operator": "in", "value": ["L-A"]},
                {"field": "direction", "operator": "in", "value": ["up"]},
            ],
        )
        self.assertEqual(run["plan"]["steps"][1]["tool"], "rank_stations")
        self.assertEqual(run["plan"]["steps"][1]["arguments"]["top_n"], 3)

    def test_station_inventory_uses_complete_entity_tool(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(
            session,
            AssistantMessageRequest(message="列出数据库中的所有地铁站"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["intent_route"], "deterministic")
        self.assertEqual(run["plan"]["steps"][0]["tool"], "list_observed_entities")
        self.assertTrue(run["tool_results"][0]["complete"])
        self.assertEqual(
            run["tool_results"][0]["summary"]["entity_count"],
            len(self.assistant.data_service.catalog()["stations"]),
        )

    def test_peak_period_and_relative_date_are_resolved_without_hiding_fixture_scope(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(
            session,
            AssistantMessageRequest(message="查询上周五晚高峰 1 号线各站进站客流，按客流量排序"),
        )
        time_range = run["plan"]["steps"][0]["arguments"]["time_range"]
        self.assertEqual(time_range["start"], "2026-07-20T17:00:00+08:00")
        self.assertEqual(time_range["end"], "2026-07-20T19:00:00+08:00")
        self.assertTrue(
            any("合成数据不含真实上周" in item for item in run["response"]["assumptions"])
        )

    def test_unknown_line_clarifies_instead_of_querying_the_whole_network(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(
            session,
            AssistantMessageRequest(message="查询 3 号线晚高峰客流为什么下降"),
        )
        self.assertEqual(run["status"], "needs_clarification")
        self.assertEqual(run["tool_results"], [])
        self.assertIn("不含 3 号线", run["response"]["follow_up_questions"][0])

    def test_multiturn_follow_up_inherits_scope_and_changes_top_n(self) -> None:
        session = self.assistant.create_session()["session_id"]
        self.assistant.message(
            session,
            AssistantMessageRequest(message="查询 2 号线各站进站客流"),
        )
        follow_up = self.assistant.message(
            session,
            AssistantMessageRequest(message="只看前三名"),
        )
        query = follow_up["plan"]["steps"][0]
        self.assertIn(
            {"field": "line_id", "operator": "in", "value": ["L-B"]},
            query["arguments"]["filters"],
        )
        self.assertEqual(follow_up["plan"]["steps"][1]["arguments"]["top_n"], 3)

    def test_independent_plan_steps_execute_concurrently(self) -> None:
        barrier = threading.Barrier(2, timeout=2)
        original = self.assistant.tools.execute

        def synchronized_execute(step_id, tool, arguments, dependencies, access_context=None):
            if step_id in {"s1", "s2"}:
                barrier.wait()
            return original(step_id, tool, arguments, dependencies, access_context)

        session = self.assistant.create_session()["session_id"]
        with patch.object(self.assistant.tools, "execute", side_effect=synchronized_execute):
            run = self.assistant.message(
                session,
                AssistantMessageRequest(message="比较 1 号线和 2 号线进站客流"),
            )
        self.assertEqual(run["status"], "completed")
        self.assertEqual(
            [item["tool"] for item in run["tool_results"][:2]], ["query_metric", "query_metric"]
        )

    def test_partial_failure_triggers_one_bounded_retry(self) -> None:
        class ReplanningProvider(FakeProvider):
            def __init__(self):
                self.plan_calls = 0

            def generate_tool_calls(self, prompt, *, context):
                self.plan_calls += 1
                if self.plan_calls == 1:
                    return super().generate_tool_calls(prompt, context=context)
                return TaskPlan.model_validate(context["original_plan"])

        provider = ReplanningProvider()
        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "replan-assistant",
            provider=provider,
        )
        session = assistant.create_session()["session_id"]
        original_execute = assistant.tools.execute
        failed_once = False

        def fail_first_step(step_id, tool, arguments, dependencies, access_context=None):
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                return ToolResult(
                    step_id=step_id,
                    tool=tool,
                    status="failed",
                    error_code="TEST_TRANSIENT_FAILURE",
                )
            return original_execute(step_id, tool, arguments, dependencies, access_context)

        with patch.object(assistant.tools, "execute", side_effect=fail_first_step):
            run = assistant.message(session, AssistantMessageRequest(message="查询进站客流"))
        self.assertEqual(provider.plan_calls, 0)
        self.assertEqual(len(run["replans"]), 1)
        self.assertEqual([item["status"] for item in run["tool_results"]], ["failed", "success"])
        self.assertIn("REPLAN", [item["state"] for item in run["events"]])

    def test_replan_reexecutes_failed_root_and_downstream_closure(self) -> None:
        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "replan-closure-assistant",
            provider=FakeProvider(),
        )
        session = assistant.create_session()["session_id"]
        original_execute = assistant.tools.execute
        failed_once = False

        def fail_first_step(step_id, tool, arguments, dependencies, access_context=None):
            nonlocal failed_once
            if not failed_once and tool == "query_metric":
                failed_once = True
                return ToolResult(
                    step_id=step_id,
                    tool=tool,
                    status="failed",
                    error_code="TEST_TRANSIENT_FAILURE",
                )
            return original_execute(step_id, tool, arguments, dependencies, access_context)

        with patch.object(assistant.tools, "execute", side_effect=fail_first_step):
            run = assistant.message(
                session,
                AssistantMessageRequest(message="查询各站进站客流，只看前三名"),
            )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(
            [item["status"] for item in run["tool_results"]],
            ["failed", "skipped", "success", "success"],
        )
        self.assertEqual(run["tool_results"][-1]["tool"], "rank_stations")
        self.assertTrue(run["evidence"]["statistics"])
        self.assertEqual(run["evidence"]["statistics"][0]["step_id"], "s102")

    def test_partial_failure_replan_cannot_add_a_new_tool(self) -> None:
        class UnsafeReplanningProvider(FakeProvider):
            def __init__(self):
                self.plan_calls = 0

            def generate_tool_calls(self, prompt, *, context):
                self.plan_calls += 1
                if self.plan_calls == 1:
                    return super().generate_tool_calls(prompt, context=context)
                return TaskPlan.model_validate(
                    {
                        "plan_id": "unsafe-fallback",
                        "task_type": "query",
                        "steps": [
                            {
                                "step_id": "s1",
                                "tool": "get_metric_catalog",
                                "arguments": {},
                            }
                        ],
                    }
                )

        provider = UnsafeReplanningProvider()
        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "unsafe-replan-assistant",
            provider=provider,
        )
        session = assistant.create_session()["session_id"]

        def fail_step(step_id, tool, arguments, dependencies, access_context=None):
            return ToolResult(
                step_id=step_id,
                tool=tool,
                status="failed",
                error_code="TEST_TRANSIENT_FAILURE",
            )

        with patch.object(assistant.tools, "execute", side_effect=fail_step):
            with self.assertRaisesRegex(ValueError, "missing required tool evidence"):
                assistant.message(session, AssistantMessageRequest(message="查询进站客流"))
        self.assertEqual(provider.plan_calls, 0)

    def test_clarification_stops_before_tools_and_persists_the_question(self) -> None:
        assistant = AssistantService(
            self.assistant.data_service,
            Path(self.temporary.name) / "clarify-assistant",
            provider=FakeProvider(),
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="查询 3 号线进站客流"))
        self.assertEqual(run["status"], "needs_clarification")
        self.assertEqual(run["tool_results"], [])
        self.assertEqual(
            run["response"]["follow_up_questions"],
            run["intent"]["ambiguities"],
        )
        self.assertEqual(len(assistant.trace_store.get_session(session).messages), 2)

    def test_trajectory_requires_gold_or_human_adoption_before_training(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(session, AssistantMessageRequest(message="查询各站进站客流"))
        self.assertTrue(run["selected_context"])
        self.assertFalse(run["dataset_eligibility"]["eligible"])
        adopted = self.assistant.record_feedback(
            run["run_id"],
            HumanFeedbackRequest(
                correction="人工复核后采纳原回答",
                accepted=True,
                adopted_response=run["response"],
            ),
        )
        self.assertTrue(adopted["dataset_eligibility"]["eligible"])
        self.assertFalse(adopted["dataset_eligibility"]["requires_human_confirmation"])
        self.assertEqual(adopted["events"][-1]["state"], "HUMAN_FEEDBACK")

    def test_dataset_export_emits_four_sample_types_and_excludes_unapproved_runs(self) -> None:
        unapproved_session = self.assistant.create_session()["session_id"]
        unapproved = self.assistant.message(
            unapproved_session, AssistantMessageRequest(message="查询各站进站客流")
        )
        approved_session = self.assistant.create_session()["session_id"]
        approved = self.assistant.message(
            approved_session, AssistantMessageRequest(message="比较 1 号线和 2 号线进站客流")
        )
        self.assistant.record_feedback(
            approved["run_id"],
            HumanFeedbackRequest(
                correction="人工复核证据与数字后采纳",
                accepted=True,
                adopted_response=approved["response"],
            ),
        )
        output = Path(self.temporary.name) / "verified-dataset"
        manifest = export_verified_trajectories(self.assistant.trace_store.runs, output)
        self.assertEqual(manifest["accepted_runs"], [approved["run_id"]])
        self.assertEqual(manifest["rejected_runs"][unapproved["run_id"]], "dataset_gate_not_passed")
        self.assertEqual(manifest["sample_counts"]["intent"], 1)
        self.assertEqual(manifest["sample_counts"]["planning"], 1)
        self.assertEqual(manifest["sample_counts"]["evidence_response"], 1)
        self.assertEqual(manifest["sample_counts"]["tool_call"], len(approved["plan"]["steps"]))
        for filename in DATASET_FILES.values():
            self.assertTrue((output / filename).is_file())
        exported = "".join(
            (output / filename).read_text(encoding="utf-8") for filename in DATASET_FILES.values()
        )
        self.assertIn(approved["run_id"], exported)
        self.assertNotIn(unapproved["run_id"], exported)

    def test_verifier_rejects_uncited_numbers(self) -> None:
        packet = EvidencePacket(question="用户声称客流为 999")
        report = verify_response(
            AssistantResponse(answer="客流为 999", evidence_refs=[]),
            packet,
        )
        self.assertFalse(report.valid)
        self.assertIn("999", report.errors[0])

    def test_verifier_rejects_entity_number_swaps_and_non_answer_numbers(self) -> None:
        packet = EvidencePacket(
            question="比较 A 站与 B 站",
            facts=[
                EvidenceItem(
                    evidence_id="ev-a",
                    step_id="s1",
                    kind="fact",
                    claim="A 站客流为 100",
                    value={"station": "A", "entries": 100},
                ),
                EvidenceItem(
                    evidence_id="ev-b",
                    step_id="s2",
                    kind="fact",
                    claim="B 站客流为 200",
                    value={"station": "B", "entries": 200},
                ),
            ],
        )
        swapped = verify_response(
            AssistantResponse(
                answer="A 站客流为 200",
                evidence_refs=["ev-a", "ev-b"],
            ),
            packet,
        )
        self.assertFalse(swapped.valid)
        self.assertIn("200", swapped.errors[0])
        hidden_number = verify_response(
            AssistantResponse(
                answer="A 站客流为 100",
                key_findings=["未经证据支持的预测为 999"],
                evidence_refs=["ev-a"],
            ),
            packet,
        )
        self.assertFalse(hidden_number.valid)
        self.assertIn("999", hidden_number.errors[0])

    def test_verifier_accepts_supported_multi_entity_numbers_in_chinese_prose(self) -> None:
        packet = EvidencePacket(
            question="比较 A 站与 B 站",
            facts=[
                EvidenceItem(
                    evidence_id="ev-a",
                    step_id="s1",
                    kind="fact",
                    claim="A 站客流为 100",
                    value={"station": "A", "entries": 100},
                ),
                EvidenceItem(
                    evidence_id="ev-b",
                    step_id="s2",
                    kind="fact",
                    claim="B 站客流为 200",
                    value={"station": "B", "entries": 200},
                ),
            ],
        )
        for answer in ("A 站客流为 100，B 站客流为 200", "A 站客流为 100 和 B 站客流为 200"):
            with self.subTest(answer=answer):
                report = verify_response(
                    AssistantResponse(answer=answer, evidence_refs=["ev-a", "ev-b"]),
                    packet,
                )
                self.assertTrue(report.valid, report.errors)

    def test_verifier_accepts_supported_dates_thousands_and_numeric_station_codes(self) -> None:
        packet = EvidencePacket(
            question="查询各站进站客流并排序",
            statistics=[
                EvidenceItem(
                    evidence_id="ev-s1",
                    step_id="s1",
                    kind="statistic",
                    claim="entries 查询返回 41 行，合计 10953",
                    value={
                        "query_ir": {
                            "time_range": {
                                "start": "2023-09-27T06:00:00+08:00",
                                "end": "2023-09-27T07:00:00+08:00",
                            },
                            "timezone": "Asia/Shanghai",
                        },
                        "rows": [
                            {"station": "0219", "entries": 963},
                            {"station": "0218", "entries": 734},
                            {"station": "0213", "entries": 616},
                        ],
                    },
                    structured_claims=[
                        StructuredClaim(
                            claim_type="metric_total",
                            metric_id="entries",
                            value=10953,
                        ),
                        StructuredClaim(
                            claim_type="result_row",
                            dimensions={"station": "0219"},
                            values={"entries": 963},
                        ),
                        StructuredClaim(
                            claim_type="result_row",
                            dimensions={"station": "0218"},
                            values={"entries": 734},
                        ),
                        StructuredClaim(
                            claim_type="result_row",
                            dimensions={"station": "0213"},
                            values={"entries": 616},
                        ),
                    ],
                )
            ],
        )
        response = AssistantResponse(
            answer=(
                "按事件时间 2023-09-27 06:00 至 07:00（Asia/Shanghai），"
                "共 41 个车站、合计 10,953 人次；0219站 963 人次，0218站 734 人次。"
            ),
            key_findings=["0219站963人次；其次为0218站734人次和0213站616人次"],
            evidence_refs=["ev-s1"],
            follow_up_questions=["ev-s1中的可见行明细被截断。"],
        )
        report = verify_response(response, packet)
        self.assertTrue(report.valid, report.errors)

        swapped = verify_response(
            AssistantResponse(
                answer="0219站 734 人次",
                evidence_refs=["ev-s1"],
            ),
            packet,
        )
        self.assertFalse(swapped.valid)
        self.assertIn("734", swapped.errors[0])

    def test_invalid_adopted_response_is_rejected_before_dataset_eligibility(self) -> None:
        session = self.assistant.create_session()["session_id"]
        run = self.assistant.message(session, AssistantMessageRequest(message="查询各站进站客流"))
        invalid_response = AssistantResponse.model_validate(
            {
                **run["response"],
                "answer": f"{run['response']['answer']}；未经证据支持的预测为 999",
            }
        )
        with self.assertRaisesRegex(ValueError, "failed evidence verification"):
            self.assistant.record_feedback(
                run["run_id"],
                HumanFeedbackRequest(
                    correction="错误地尝试采纳未核验数字",
                    accepted=True,
                    adopted_response=invalid_response,
                ),
            )
        unchanged = self.assistant.get_run(run["run_id"])
        self.assertEqual(unchanged["human_feedback"], [])
        self.assertFalse(unchanged["dataset_eligibility"]["eligible"])

    def test_shadow_human_gate_requires_real_action_rows(self) -> None:
        case = {
            "expected_status": "completed",
            "expected_task_type": "alert",
            "expected_tools": [],
            "required_states": [],
            "expected_evidence_kinds": [],
            "artifact_required": False,
            "human_gate": True,
            "non_causal": False,
        }
        run = {
            "status": "completed",
            "intent": {"task_type": "alert"},
            "response": {"recommendations": ["关闭车站"], "evidence_refs": ["ev-1"]},
            "verification": {"valid": True},
            "tool_results": [],
            "events": [],
            "evidence": {"knowledge_sources": [{"kind": "knowledge"}]},
        }
        self.assertFalse(shadow_checks(case, run)["human_gate"])


if __name__ == "__main__":
    unittest.main()
