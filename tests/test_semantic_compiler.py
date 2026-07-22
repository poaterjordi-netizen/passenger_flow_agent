from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from metro_agent.api.service import SyntheticApiService
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.schemas import (
    AssistantMessageRequest,
    AssistantResponse,
    SemanticEntityMention,
    SemanticFrame,
    SemanticMetricMention,
)
from scripts.evaluate_semantic_expressions import validate_cases

ROOT = Path(__file__).resolve().parents[1]


class ScriptedSemanticProvider:
    name = "scripted-gpt-5.6-sol"
    model = "gpt-5.6-sol"

    def __init__(self, frames: list[SemanticFrame]) -> None:
        self.frames = list(frames)
        self.usage_records: list[dict[str, object]] = []

    def generate_structured(self, prompt, schema, *, context):
        self.usage_records.append(
            {
                "api_calls": 1,
                "completed": True,
                "failed": False,
                "input_tokens": 10,
                "output_tokens": 10,
                "total_tokens": 20,
            }
        )
        if schema is SemanticFrame:
            return self.frames.pop(0)
        if schema is AssistantResponse:
            evidence = context["evidence"]
            refs = [
                item["evidence_id"]
                for group in (
                    "facts",
                    "statistics",
                    "charts",
                    "model_outputs",
                    "knowledge_sources",
                )
                for item in evidence[group]
            ]
            return AssistantResponse(
                answer="数据库证据与一般知识推断已分开说明。",
                key_findings=["数据库结论只采用本次证据，一般知识仅作为待验证解释。"],
                evidence_refs=refs,
                limitations=["一般知识不代表数据库已经证明因果关系。"],
            )
        raise AssertionError(f"unexpected schema {schema}")

    def generate_tool_calls(self, prompt, *, context):
        raise AssertionError("planner must remain deterministic")

    def synthesize_from_evidence(self, question, evidence, *, context):
        raise AssertionError("orchestrator uses the structured synthesis path")

    def stream_text(self, prompt, *, context):
        return iter(())


class InvalidSynthesisProvider(ScriptedSemanticProvider):
    def generate_structured(self, prompt, schema, *, context):
        if schema is AssistantResponse:
            self.usage_records.append(
                {
                    "api_calls": 1,
                    "completed": True,
                    "failed": False,
                    "input_tokens": 10,
                    "output_tokens": 10,
                    "total_tokens": 20,
                }
            )
            return AssistantResponse(answer="数据库共有 999999 人。")
        return super().generate_structured(prompt, schema, context=context)


class SemanticCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.data_service = SyntheticApiService(
            ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=root / "audits",
                environment="test",
            )
        )
        self.root = root

    def assistant(self, frames: list[SemanticFrame]) -> tuple[AssistantService, ScriptedSemanticProvider]:
        provider = ScriptedSemanticProvider(frames)
        return (
            AssistantService(self.data_service, self.root / "assistant", provider=provider),
            provider,
        )

    def test_novel_wording_uses_model_semantics_then_deterministic_entity_linking(self) -> None:
        frame = SemanticFrame(
            route="data",
            goal="描述一号线在数据库观测窗内的客流画像",
            operations=["describe", "aggregate"],
            target_kind="line",
            entity_mentions=[SemanticEntityMention(type="line", raw_text="一号线")],
            metric_mentions=[
                SemanticMetricMention(
                    raw_text="客流", candidate_metrics=["entries", "exits"], resolution="candidate"
                )
            ],
            evidence_requirements=["database_rows"],
            defaults_allowed=True,
            confidence=0.97,
        )
        assistant, provider = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="劳驾把一号线在库里的画像讲明白"),
        )

        self.assertEqual(run["semantic_source"], "model")
        self.assertEqual(run["intent_route"], "semantic_model")
        self.assertEqual(run["semantic_frame"]["route"], "data")
        self.assertEqual(run["entity_resolutions"][0]["selected_id"], "L-A")
        self.assertEqual(run["metric_resolutions"][0]["selected_metric"], "entries")
        self.assertEqual(run["operation_ir"]["operation"], "describe_entity")
        self.assertEqual(run["plan"]["steps"][0]["tool"], "describe_observed_entity")
        self.assertEqual(run["model_runtime"]["provider_calls"], 1)
        self.assertEqual(len(provider.usage_records), 1)

    def test_hybrid_route_queries_data_then_calls_model_for_separated_explanation(self) -> None:
        frame = SemanticFrame(
            route="hybrid",
            goal="诊断一号线客流变化并给出一般机制解释",
            operations=["diagnose", "explain"],
            target_kind="line",
            entity_mentions=[SemanticEntityMention(type="line", raw_text="一号线")],
            metric_mentions=[
                SemanticMetricMention(
                    raw_text="进站客流", candidate_metrics=["entries"], resolution="exact"
                )
            ],
            evidence_requirements=["database_rows", "general_knowledge"],
            confidence=0.95,
        )
        assistant, provider = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="一号线进站客流为何变化，通常又受哪些因素影响？"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["operation_ir"]["answer_policy"], "llm_hybrid")
        self.assertTrue(run["tool_results"])
        self.assertEqual(run["model_runtime"]["provider_calls"], 2)
        self.assertEqual(len(provider.usage_records), 2)
        self.assertTrue(run["verification"]["valid"])

    def test_model_cannot_downgrade_explicit_diagnosis_to_comparison(self) -> None:
        frame = SemanticFrame(
            route="external",
            goal="比较一号线晚高峰客流变化",
            operations=["compare"],
            target_kind="line",
            entity_mentions=[SemanticEntityMention(type="line", raw_text="1号线")],
            metric_mentions=[
                SemanticMetricMention(
                    raw_text="客流", candidate_metrics=["entries"], resolution="candidate"
                )
            ],
            evidence_requirements=["database_rows"],
            confidence=0.91,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="昨天 1 号线晚高峰客流为什么下降"),
        )

        self.assertEqual(run["semantic_source"], "model")
        self.assertIn("diagnose", run["semantic_frame"]["operations"])
        self.assertEqual(run["intent"]["task_type"], "diagnosis")
        self.assertEqual(run["operation_ir"]["operation"], "diagnosis")
        self.assertIn(
            "diagnose_flow_change", [step["tool"] for step in run["plan"]["steps"]]
        )

    def test_diagnosis_takes_priority_when_comparison_is_supporting_evidence(self) -> None:
        frame = SemanticFrame(
            route="data",
            goal="诊断一号线客流下降并比较基准",
            operations=["diagnose", "compare"],
            target_kind="line",
            entity_mentions=[SemanticEntityMention(type="line", raw_text="1号线")],
            evidence_requirements=["database_rows"],
            defaults_allowed=True,
            confidence=0.95,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="昨天 1 号线晚高峰客流为什么下降"),
        )

        self.assertEqual(run["intent"]["task_type"], "diagnosis")
        self.assertEqual(run["operation_ir"]["operation"], "diagnosis")
        self.assertIn(
            "diagnose_flow_change", [step["tool"] for step in run["plan"]["steps"]]
        )

    def test_invalid_model_synthesis_falls_back_to_verified_evidence_rendering(self) -> None:
        frame = SemanticFrame(
            route="data",
            goal="按进站量给车站排序",
            operations=["rank"],
            target_kind="station",
            metric_mentions=[
                SemanticMetricMention(
                    raw_text="进站量", candidate_metrics=["entries"], resolution="exact"
                )
            ],
            evidence_requirements=["database_rows"],
            confidence=0.99,
        )
        provider = InvalidSynthesisProvider([frame])
        assistant = AssistantService(
            self.data_service,
            self.root / "invalid-synthesis-assistant",
            provider=provider,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session, AssistantMessageRequest(message="按进站量给车站排个名")
        )

        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["verification"]["valid"])
        self.assertNotIn("999999", run["response"]["answer"])
        self.assertIn("VERIFICATION_FALLBACK", [item["state"] for item in run["events"]])

    def test_collection_mentions_are_dimensions_not_missing_named_entities(self) -> None:
        frame = SemanticFrame(
            route="data",
            goal="查询一号线各站进站量",
            operations=["query"],
            target_kind="station",
            entity_mentions=[
                SemanticEntityMention(type="line", raw_text="一号线", role="context"),
                SemanticEntityMention(
                    type="station", raw_text="各站", role="subject", reference="collection"
                ),
            ],
            metric_mentions=[
                SemanticMetricMention(
                    raw_text="进站量", candidate_metrics=["entries"], resolution="exact"
                )
            ],
            evidence_requirements=["database_rows"],
            confidence=0.99,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session, AssistantMessageRequest(message="查一号线各站进站量")
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["entity_resolutions"][1]["status"], "not_applicable")
        self.assertEqual(run["plan"]["steps"][0]["arguments"]["dimensions"], ["station"])
        self.assertEqual(run["model_runtime"]["provider_calls"], 1)

    def test_external_route_is_explicit_instead_of_fabricating_current_facts(self) -> None:
        frame = SemanticFrame(
            route="external",
            goal="判断明天天气对客流的影响",
            operations=["explain"],
            target_kind="dataset",
            evidence_requirements=["external_live_data"],
            confidence=0.98,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session, AssistantMessageRequest(message="明天天气会怎样影响地铁客流？")
        )

        self.assertEqual(run["operation_ir"]["operation"], "external_answer")
        self.assertEqual(run["plan"]["steps"][0]["tool"], "prepare_external_context")
        self.assertIn("尚未接入对应实时工具", run["response"]["answer"])
        self.assertEqual(run["model_runtime"]["provider_calls"], 1)

    def test_general_route_does_not_turn_optional_preferences_into_database_ambiguity(self) -> None:
        frame = SemanticFrame(
            route="general",
            goal="比较两个城市的一般旅游适宜性",
            operations=["compare", "explain"],
            target_kind="place",
            entity_mentions=[
                SemanticEntityMention(type="place", raw_text="北京"),
                SemanticEntityMention(type="place", raw_text="上海"),
            ],
            evidence_requirements=["general_knowledge"],
            material_missing_fields=["用户未给出个人旅游偏好"],
            confidence=0.92,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session, AssistantMessageRequest(message="比较北京和上海哪个更适合旅游")
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["intent"]["task_type"], "general")
        self.assertEqual(run["operation_ir"]["operation"], "general_answer")
        self.assertFalse(run["intent"]["needs_clarification"])
        self.assertTrue(run["verification"]["valid"])
        self.assertTrue(
            all(item["status"] == "not_applicable" for item in run["entity_resolutions"])
        )

    def test_semantic_memory_can_be_inherited_without_copying_passenger_facts(self) -> None:
        frames = [
            SemanticFrame(
                route="data",
                goal="查询一号线各站进站量",
                operations=["query"],
                target_kind="line",
                entity_mentions=[SemanticEntityMention(type="line", raw_text="一号线")],
                metric_mentions=[
                    SemanticMetricMention(
                        raw_text="进站量", candidate_metrics=["entries"], resolution="exact"
                    )
                ],
                evidence_requirements=["database_rows"],
                confidence=0.98,
            ),
            SemanticFrame(
                route="data",
                goal="在上一轮范围内只保留排名结果",
                operations=["rank"],
                target_kind="station",
                evidence_requirements=["database_rows"],
                inherit_context=True,
                confidence=0.96,
            ),
        ]
        assistant, _ = self.assistant(frames)
        session = assistant.create_session()["session_id"]
        first_run = assistant.message(
            session, AssistantMessageRequest(message="查一号线各站进站量")
        )
        run = assistant.message(session, AssistantMessageRequest(message="那就只看排名呢？"))

        self.assertEqual(
            first_run["semantic_memory_snapshot"]["current_entities"]["line"], ["L-A"]
        )
        self.assertEqual(first_run["semantic_memory_snapshot"]["current_metric"], "entries")
        filters = run["plan"]["steps"][0]["arguments"]["filters"]
        self.assertIn({"field": "line_id", "operator": "in", "value": ["L-A"]}, filters)
        self.assertEqual(run["intent"]["metrics"], ["entries"])
        session_record = assistant.trace_store.get_session(session)
        self.assertEqual(session_record.semantic_memory.current_entities["line"], ["L-A"])
        self.assertFalse(hasattr(session_record.semantic_memory, "passenger_flow_rows"))

    def test_invalid_or_invented_model_entity_falls_back_for_the_whole_run(self) -> None:
        frame = SemanticFrame(
            route="data",
            goal="描述二号线",
            operations=["describe"],
            target_kind="line",
            entity_mentions=[SemanticEntityMention(type="line", raw_text="二号线")],
            evidence_requirements=["database_rows"],
            confidence=0.99,
        )
        assistant, _ = self.assistant([frame])
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="介绍一下一号线"))

        self.assertEqual(run["semantic_source"], "deterministic_fallback")
        self.assertEqual(run["entity_resolutions"][0]["selected_id"], "L-A")
        self.assertEqual(run["model_egress"][0]["status"], "failed")
        self.assertIn("SEMANTIC_FALLBACK", [item["state"] for item in run["events"]])

    def test_semantic_schema_has_no_resolved_id_or_sql_escape_hatch(self) -> None:
        with self.assertRaises(ValidationError):
            SemanticFrame.model_validate(
                {
                    "route": "data",
                    "goal": "query",
                    "operations": ["query"],
                    "entity_mentions": [
                        {"type": "line", "raw_text": "一号线", "resolved_id": "L-A"}
                    ],
                    "sql": "select * from anything",
                    "confidence": 1,
                }
            )

    def test_open_expression_fixture_is_machine_valid_and_category_diverse(self) -> None:
        cases = validate_cases(ROOT / "examples/semantic_expression_cases.json")
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["case_id"] for case in cases}), 20)
        categories = {case["category"] for case in cases}
        self.assertTrue({"paraphrase", "typo", "hybrid", "multiturn", "external"} <= categories)


if __name__ == "__main__":
    unittest.main()
