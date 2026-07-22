import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from metro_agent.access import AccessContext, AuthorizationService

from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.service import (
    MetroflowReadOnlyDataService,
    ProductionSourcePolicy,
    SyntheticApiService,
    create_data_service,
)
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.orchestrator import AssistantService
from metro_agent.assistant.provider import FakeProvider
from metro_agent.assistant.schemas import (
    AssistantMessageRequest,
    AssistantResponse,
    ToolResult,
)
from metro_agent.assistant.evidence import build_evidence_packet
from metro_agent.assistant.tool_registry import ToolRegistry
from metro_agent.assistant.verifier import verify_response
from metro_agent.database import (
    STATION_FLOW_MAPPING_VERSION,
    DatabaseQueryResult,
    station_flow_mapping_hash,
)
from metro_agent.mcp_facade import MetroMcpFacade
from metro_agent.source_registry import load_source_registration

ROOT = Path(__file__).resolve().parents[1]


class StubDatabase:
    def __init__(self, *, truncated: bool = False) -> None:
        self.truncated = truncated
        self.calls = []

    def query_station_flow_day(self, service_date, **kwargs):
        self.calls.append((service_date, kwargs))
        rows = [
            {
                "StationID": "S-A",
                "StationName": "Alpha",
                "LineID": "L-1",
                "LineName": "Line 1",
                "StartTime": datetime(2026, 7, 20, 8, 0),
                "EndTime": datetime(2026, 7, 20, 8, 10),
                "InFlow": 10,
                "OutFlow": 4,
            },
            {
                "StationID": "S-A",
                "StationName": "Alpha",
                "LineID": "L-1",
                "LineName": "Line 1",
                "StartTime": datetime(2026, 7, 20, 8, 10),
                "EndTime": datetime(2026, 7, 20, 8, 20),
                "InFlow": 5,
                "OutFlow": 2,
            },
            {
                "StationID": "S-B",
                "StationName": "Beta",
                "LineID": "L-1",
                "LineName": "Line 1",
                "StartTime": datetime(2026, 7, 20, 8, 0),
                "EndTime": datetime(2026, 7, 20, 8, 10),
                "InFlow": 7,
                "OutFlow": 3,
            },
        ]
        return DatabaseQueryResult(
            dataset="station_flow_day",
            rows=rows,
            sql_template="fixed allowlisted station-flow template",
            parameter_count=3,
            tls_cipher="TLS_FAKE_FOR_TEST",
            truncated=self.truncated,
        )


def shadow_settings(root: Path, **overrides) -> ApiSettings:
    registry_path = root / "source-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "sources": [
                    {
                        "logical_dataset": "fact_station_flow_actual",
                        "city": "beijing-test",
                        "dataset_role": "actual",
                        "source_version": "approved-test-v1",
                        "physical_mapping_ref": "station_flow_day",
                        "physical_mapping_version": STATION_FLOW_MAPPING_VERSION,
                        "physical_mapping_hash": station_flow_mapping_hash(),
                        "time_grain": "10m",
                        "timezone": "Asia/Shanghai",
                        "status": "approved",
                        "quality_status": "pass",
                        "semantic_status": "verified",
                        "quality_gate": "station-flow-actual-quality-v1",
                        "access_policy": "station-flow-aggregate-read-v1",
                        "default_time_range": {
                            "start": "2026-07-20T08:00:00+08:00",
                            "end": "2026-07-20T09:00:00+08:00",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    values = {
        "metrics_path": ROOT / "examples/synthetic_data/metrics.json",
        "data_path": ROOT / "examples/synthetic_data/passenger_flow.csv",
        "audit_dir": root / "audits",
        "environment": "test",
        "access_token": "test-access-token",
        "data_mode": "production-shadow",
        "production_city": "beijing-test",
        "production_source_version": "approved-test-v1",
        "production_time_grain": "10m",
        "production_source_status": "approved",
        "production_default_start": "2026-07-20T08:00:00+08:00",
        "production_default_end": "2026-07-20T09:00:00+08:00",
        "production_registry_path": registry_path,
        "access_subject_id": "test-shadow-reader",
        "access_tenant_or_department": "test-department",
        "access_roles": ("shadow-reader",),
        "access_allowed_cities": ("beijing-test",),
        "access_allowed_metrics": ("entries", "exits", "net_inflow"),
        "access_allowed_dataset_roles": ("actual",),
        "access_max_time_range_hours": 24,
        "access_row_limit": 100,
        "access_export_policy": "deny",
        "access_policy_snapshot_id": "test-access-policy-v1",
        "model_endpoint_policy_id": "test-model-policy-v1",
        "model_data_egress": "deny",
    }
    values.update(overrides)
    return ApiSettings(**values)


def shadow_query(**overrides) -> QueryRequest:
    values = {
        "metric": "entries",
        "metric_version": "1.0.0",
        "city": "beijing-test",
        "dataset_role": "actual",
        "source_version": "approved-test-v1",
        "time_grain": "10m",
        "time_range": {
            "start": "2026-07-20T08:00:00+08:00",
            "end": "2026-07-20T09:00:00+08:00",
        },
        "dimensions": ["station"],
        "filters": [],
        "order_by": [{"field": "entries", "direction": "desc"}],
        "limit": 10,
    }
    values.update(overrides)
    return QueryRequest.model_validate(values)


class ProductionShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def service(self, database=None) -> MetroflowReadOnlyDataService:
        settings = shadow_settings(self.root)
        policy = ProductionSourcePolicy.from_settings(settings)
        return MetroflowReadOnlyDataService(settings, database or StubDatabase(), policy)

    def access(self) -> AccessContext:
        return shadow_settings(self.root).access_context()

    def test_source_metadata_fails_closed_until_approved(self) -> None:
        unauthenticated = shadow_settings(self.root, access_token=None)
        with self.assertRaisesRegex(ValueError, "access token"):
            create_data_service(unauthenticated, database=StubDatabase())

        with self.assertRaisesRegex(ValueError, "access context is incomplete"):
            create_data_service(
                shadow_settings(self.root, access_subject_id=None), database=StubDatabase()
            )

        settings = shadow_settings(self.root, production_source_status="blocked")
        with self.assertRaisesRegex(ValueError, "not approved"):
            create_data_service(settings, database=StubDatabase())

        incomplete = shadow_settings(self.root, production_source_version=None)
        with self.assertRaisesRegex(ValueError, "metadata is incomplete"):
            create_data_service(incomplete, database=StubDatabase())

        quality_blocked = shadow_settings(self.root)
        registry = json.loads(quality_blocked.production_registry_path.read_text(encoding="utf-8"))
        registry["sources"][0]["quality_status"] = "warning"
        quality_blocked.production_registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "quality gate did not pass"):
            create_data_service(quality_blocked, database=StubDatabase())

        mismatched = shadow_settings(self.root)
        registry = json.loads(mismatched.production_registry_path.read_text(encoding="utf-8"))
        registry["sources"][0]["physical_mapping_hash"] = "0" * 64
        mismatched.production_registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mapping hash does not match"):
            ProductionSourcePolicy.from_settings(mismatched)

        verified_tls = shadow_settings(self.root)
        with self.assertRaisesRegex(ValueError, "verified TLS"):
            create_data_service(
                verified_tls,
                environment={
                    "METRO_DB_HOST": "db.test",
                    "METRO_DB_USER": "reader",
                    "METRO_DB_PASSWORD": "test-only",
                    "METRO_DB_NAME": "metro-test",
                    "METRO_DB_ALLOW_INSECURE_TLS": "true",
                },
            )

    def test_source_aliases_are_rejected_before_execution(self) -> None:
        settings = shadow_settings(self.root)
        payload = json.loads(settings.production_registry_path.read_text(encoding="utf-8"))
        payload["sources"][0]["source_version"] = "approved-current"
        settings.production_registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "immutable source_version"):
            load_source_registration(
                settings.production_registry_path,
                logical_dataset="fact_station_flow_actual",
                city="beijing-test",
                source_version="approved-current",
            )

    def test_shadow_query_aggregates_bounded_rows_and_records_provenance(self) -> None:
        database = StubDatabase()
        result = self.service(database).query(shadow_query(), self.access())

        self.assertEqual(
            result["rows"],
            [{"station": "S-A", "entries": 15}, {"station": "S-B", "entries": 7}],
        )
        self.assertEqual(result["data_scope"], "production-shadow")
        self.assertEqual(result["provenance"]["city"], "beijing-test")
        self.assertEqual(result["provenance"]["quality_status"], "pass")
        self.assertEqual(result["provenance"]["runtime_quality_status"], "pass")
        self.assertEqual(result["provenance"]["missing_row_count"], 0)
        self.assertEqual(result["provenance"]["invalid_row_count"], 0)
        self.assertTrue(result["provenance"]["query_template_hash"])
        self.assertEqual(result["provenance"]["transaction_mode"], "read_only_rollback")
        self.assertFalse(result["provenance"]["truncated"])
        _, kwargs = database.calls[0]
        self.assertIsNone(kwargs["start_time"].tzinfo)
        self.assertIsNone(kwargs["end_time"].tzinfo)
        self.assertEqual(kwargs["limit"], 50_000)

        limited = self.service(StubDatabase()).query(shadow_query(limit=1), self.access())
        self.assertTrue(limited["provenance"]["truncated"])
        self.assertEqual(limited["provenance"]["total_group_count"], 2)

    def test_production_missing_or_invalid_flow_values_fail_closed(self) -> None:
        settings = shadow_settings(self.root)
        invalid_values = [None, "10", float("nan"), -1]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                database = StubDatabase()
                original = database.query_station_flow_day

                def query(*args, **kwargs):
                    result = original(*args, **kwargs)
                    result.rows[0]["InFlow"] = invalid
                    return result

                database.query_station_flow_day = query
                service = MetroflowReadOnlyDataService(
                    settings,
                    database,
                    ProductionSourcePolicy.from_settings(settings),
                )
                with self.assertRaisesRegex(ValueError, "production source has"):
                    service.query(shadow_query(), self.access())

        database = StubDatabase()
        original = database.query_station_flow_day

        def missing(*args, **kwargs):
            result = original(*args, **kwargs)
            result.rows[0].pop("InFlow")
            return result

        database.query_station_flow_day = missing
        service = MetroflowReadOnlyDataService(
            settings,
            database,
            ProductionSourcePolicy.from_settings(settings),
        )
        with self.assertRaisesRegex(ValueError, "missing required value"):
            service.query(shadow_query(), self.access())

    def test_registration_pass_is_not_reported_as_runtime_quality_pass(self) -> None:
        catalog = self.service().catalog(self.access())
        quality = self.service().quality_status(self.access())
        self.assertEqual(catalog["registration_quality_status"], "pass")
        self.assertEqual(catalog["runtime_quality_status"], "unknown")
        self.assertEqual(catalog["quality_status"], "unknown")
        self.assertEqual(quality["status"], "unknown")

    def test_shadow_rejects_scope_drift_unsupported_metrics_and_truncation(self) -> None:
        service = self.service()
        with self.assertRaisesRegex(PermissionError, "city"):
            service.query(shadow_query(city="other-city"), self.access())
        with self.assertRaisesRegex(PermissionError, "dataset role"):
            service.query(shadow_query(dataset_role="forecast"), self.access())
        with self.assertRaisesRegex(PermissionError, "metric"):
            service.query(
                shadow_query(
                    metric="transfers",
                    order_by=[{"field": "transfers", "direction": "desc"}],
                ),
                self.access(),
            )
        with self.assertRaisesRegex(PermissionError, "time range"):
            service.query(
                shadow_query(
                    time_range={
                        "start": "2026-07-20T08:00:00+08:00",
                        "end": "2026-07-21T09:00:00+08:00",
                    }
                ),
                self.access(),
            )
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.service(StubDatabase(truncated=True)).query(shadow_query(), self.access())

    def test_production_shadow_completes_the_governed_assistant_loop(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="查询进站客流"))

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["selected_context"]["data_scope"], "production-shadow")
        self.assertEqual(run["intent"]["city"], "beijing-test")
        self.assertEqual(run["intent"]["source_version"], "approved-test-v1")
        self.assertTrue(run["verification"]["valid"])
        self.assertIn("production-shadow", run["response"]["limitations"][-1])
        self.assertEqual(run["evidence"]["facts"][0]["metadata"]["quality_status"], "pass")
        self.assertEqual(run["model_egress"], [])

    def test_station_inventory_query_is_not_misclassified_as_ambiguous(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "station-inventory-assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="列出数据库中的所有地铁站"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["intent_route"], "deterministic")
        self.assertTrue(run["verification"]["valid"])
        self.assertEqual(run["plan"]["steps"][0]["tool"], "list_observed_entities")
        result = run["tool_results"][0]
        self.assertTrue(result["complete"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["summary"]["entity_count"], 2)
        self.assertFalse(result["summary"]["authoritative_master"])
        self.assertEqual(
            result["rows"],
            [
                {"station": "S-A", "station_name": "Alpha"},
                {"station": "S-B", "station_name": "Beta"},
            ],
        )
        self.assertEqual(len(run["evidence"]["facts"][0]["value"]["rows"]), 2)
        self.assertIn("Alpha（S-A）", run["response"]["answer"])
        self.assertIn("不是对数据库全部表", result["warnings"][0])

        line_session = assistant.create_session()["session_id"]
        line_run = assistant.message(
            line_session,
            AssistantMessageRequest(message="列出数据库中的所有地铁线路"),
        )
        self.assertEqual(line_run["status"], "completed")
        self.assertEqual(line_run["intent_route"], "deterministic")
        self.assertEqual(
            line_run["tool_results"][0]["rows"],
            [{"line": "L-1", "line_name": "Line 1"}],
        )

    def test_line_situation_typo_queries_real_shadow_rows_instead_of_general_gpt(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "line-situation-assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="给出数据库中北京地铁一号线到情况"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["intent"]["task_type"], "query")
        self.assertEqual(run["operation_ir"]["operation"], "describe_entity")
        self.assertEqual(run["operation_ir"]["target_query"], "L-1")
        self.assertEqual(run["entity_resolutions"][0]["selected_name"], "Line 1")
        self.assertEqual(run["plan"]["steps"][0]["tool"], "describe_observed_entity")
        self.assertEqual(run["model_runtime"]["model_calls"], 0)
        self.assertEqual(
            run["tool_results"][0]["rows"],
            [{"line": "L-1", "line_name": "Line 1", "entries": 22}],
        )
        self.assertIn("进站量（entries）汇总为 22", run["response"]["answer"])
        self.assertNotIn("未读取 metroflow", run["response"]["answer"])
        self.assertTrue(run["verification"]["valid"])

    def test_event_forecast_request_returns_real_context_and_admission_requirements(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "forecast-readiness-assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="奥体中心有 4 万人演唱会，预测客流并给出建议"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["verification"]["valid"])
        self.assertEqual(
            [step["tool"] for step in run["plan"]["steps"]],
            [
                "query_metric",
                "get_data_quality_status",
                "assess_event_forecast_readiness",
            ],
        )
        self.assertEqual(run["intent"]["event_spec"]["impacted_stations"], [])
        self.assertIsNone(run["intent"]["event_spec"]["target_date"])
        readiness = run["tool_results"][2]
        self.assertEqual(readiness["status"], "success")
        self.assertEqual(readiness["summary"]["forecast_status"], "not_admitted")
        self.assertFalse(readiness["summary"]["numeric_forecast_generated"])
        self.assertIn("未生成数值预测", run["response"]["answer"])
        self.assertTrue(run["response"]["recommendations"])

    def test_unadmitted_task_uses_readiness_plan_instead_of_validation_error(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "generic-readiness-assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(
            session,
            AssistantMessageRequest(message="昨天客流为什么下降？"),
        )

        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["verification"]["valid"])
        self.assertEqual(
            [step["tool"] for step in run["plan"]["steps"]],
            ["get_data_quality_status", "assess_task_readiness"],
        )
        self.assertIn("CAPABILITY_FALLBACK", [event["state"] for event in run["events"]])
        self.assertIn("未生成运营结论", run["response"]["answer"])

    def test_production_assistant_is_disabled_until_explicit_promotion(self) -> None:
        assistant = AssistantService(
            self.service(),
            self.root / "disabled-assistant",
            provider=FakeProvider(),
            default_access_context=self.access(),
        )
        with self.assertRaisesRegex(PermissionError, "offline validation"):
            assistant.create_session()

    def test_denied_model_egress_uses_deterministic_renderer(self) -> None:
        class CountingProvider:
            name = "external-model-test-double"

            def __init__(self) -> None:
                self.calls = 0

            def generate_structured(self, prompt, schema, *, context):
                self.calls += 1
                raise AssertionError("model must not receive production context")

            def generate_tool_calls(self, prompt, *, context):
                self.calls += 1
                raise AssertionError("model must not generate production plans")

            def synthesize_from_evidence(self, question, evidence, *, context):
                self.calls += 1
                raise AssertionError("production evidence egress is denied")

            def stream_text(self, prompt, *, context):
                self.calls += 1
                return iter(())

        provider = CountingProvider()
        assistant = AssistantService(
            self.service(),
            self.root / "egress-assistant",
            provider=provider,
            default_access_context=self.access(),
            production_enabled=True,
        )
        session = assistant.create_session()["session_id"]
        run = assistant.message(session, AssistantMessageRequest(message="查询进站客流"))
        self.assertEqual(run["status"], "completed")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(run["model_egress"]), 1)
        self.assertEqual(
            [item["purpose"] for item in run["model_egress"]],
            ["semantic_compile"],
        )
        self.assertTrue(all(item["decision"] == "denied" for item in run["model_egress"]))
        self.assertTrue(all(item["status"] == "not_called" for item in run["model_egress"]))
        self.assertTrue(all(item["exact_payload_hash"] for item in run["model_egress"]))

    def test_production_registry_physically_excludes_unadmitted_tools(self) -> None:
        registry = ToolRegistry(self.service(), self.root / "reports")
        self.assertNotIn("export_report", registry.names)
        self.assertNotIn("build_daily_report", registry.names)
        self.assertNotIn("run_reference_day_forecast", registry.names)
        self.assertNotIn("query_bus_transactions", registry.names)
        self.assertNotIn("resolve_metro_entity", registry.names)
        self.assertIn("assess_event_forecast_readiness", registry.names)
        self.assertIn("assess_task_readiness", registry.names)

    def test_blocked_quality_cannot_be_adopted_as_a_valid_answer(self) -> None:
        packet = build_evidence_packet(
            "query",
            [
                ToolResult(
                    step_id="s1",
                    tool="query_metric",
                    status="success",
                    summary={
                        "claim": "entries total 10",
                        "provenance": {"quality_status": "blocked"},
                    },
                    rows=[{"entries": 10}],
                )
            ],
        )
        report = verify_response(
            AssistantResponse(answer="entries total 10", evidence_refs=["ev-s1"]), packet
        )
        self.assertFalse(report.valid)
        self.assertIn("blocked data quality", report.errors[0])


class McpFacadeTests(unittest.TestCase):
    def test_facade_exposes_only_governed_tools_and_returns_tool_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ApiSettings(
                metrics_path=ROOT / "examples/synthetic_data/metrics.json",
                data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
                audit_dir=root / "audits",
                environment="test",
            )
            registry = ToolRegistry(SyntheticApiService(settings), root / "reports")
            facade = MetroMcpFacade(registry)
            names = {item["name"] for item in facade.list_tools()}
            self.assertIn("query_metric", names)
            self.assertIn("execute_query_ir", names)
            self.assertIn("search_entities", names)
            self.assertIn("list_metrics", names)
            self.assertIn("list_available_dates", names)
            self.assertIn("list_observed_entities", names)
            self.assertNotIn("rank_stations", names)
            self.assertNotIn("calculate_growth", names)
            self.assertNotIn("execute_sql", names)
            self.assertNotIn("list_all_tables", names)
            result = facade.call_tool(
                "query_metric",
                QueryRequest.model_validate(
                    {
                        "metric": "entries",
                        "time_range": {
                            "start": "2026-07-20T08:00:00+08:00",
                            "end": "2026-07-20T09:00:00+08:00",
                        },
                        "dimensions": [],
                        "filters": [],
                        "limit": 10,
                    }
                ).model_dump(mode="json"),
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["summary"]["provenance"]["quality_status"], "pass")
            catalog_result = facade.call_tool("list_metrics", {})
            self.assertEqual(
                catalog_result["coverage"]["coverage_type"], "registered_catalog"
            )
            self.assertTrue(catalog_result["coverage"]["complete"])
            entity_result = facade.call_tool(
                "search_entities",
                {
                    "raw_text": "一号线",
                    "entity_type": "line",
                    "query": QueryRequest.model_validate(
                        {
                            "metric": "entries",
                            "time_range": {
                                "start": "2026-07-20T08:00:00+08:00",
                                "end": "2026-07-20T09:00:00+08:00",
                            },
                            "dimensions": ["line"],
                            "filters": [],
                            "limit": 10,
                        }
                    ).model_dump(mode="json"),
                },
            )
            self.assertEqual(entity_result["rows"][0]["id"], "L-A")
            with self.assertRaisesRegex(ValueError, "not admitted"):
                facade.call_tool("execute_sql", {"sql": "SELECT 1"})
            with self.assertRaisesRegex(ValueError, "not admitted"):
                facade.call_tool(
                    "rank_stations",
                    {"rows": [{"station": "FAKE", "entries": 999999}]},
                )


class AccessAndCompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        settings = ApiSettings(
            metrics_path=ROOT / "examples/synthetic_data/metrics.json",
            data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
            audit_dir=self.root / "audits",
            environment="test",
        )
        self.service = SyntheticApiService(settings)

    @staticmethod
    def context(subject: str) -> AccessContext:
        return AccessContext(
            subject_id=subject,
            tenant_or_department="department-a",
            roles=("reader",),
            allowed_cities=("synthetic",),
            allowed_metrics=("entries",),
            allowed_dataset_roles=("actual",),
            max_time_range_hours=24,
            row_limit=100,
            export_policy="deny",
            policy_snapshot_id="policy-a-v1",
            model_endpoint_policy_id="model-deny-v1",
            model_data_egress="deny",
        )

    @staticmethod
    def query(limit: int = 100) -> QueryRequest:
        return QueryRequest.model_validate(
            {
                "metric": "entries",
                "city": "synthetic",
                "source_version": "synthetic-v1",
                "time_range": {
                    "start": "2026-07-20T08:00:00+08:00",
                    "end": "2026-07-20T10:00:00+08:00",
                },
                "dimensions": ["station"],
                "filters": [],
                "limit": limit,
            }
        )

    def test_production_model_egress_requires_exact_endpoint_binding(self) -> None:
        identity = {
            "provider": "openai-compatible",
            "model": "approved-model",
            "target_hash": "a" * 64,
        }
        context = self.context("reader-a").model_copy(
            update={
                "model_data_egress": "aggregate-approved",
                "model_intent_egress": "metadata-approved",
                "model_allowed_provider": identity["provider"],
                "model_allowed_model": identity["model"],
                "model_allowed_target_hash": identity["target_hash"],
            }
        )
        self.assertTrue(
            AuthorizationService.may_send_evidence_to_model(context, "production-shadow", identity)
        )
        self.assertTrue(
            AuthorizationService.may_send_intent_to_model(context, "production-shadow", identity)
        )
        self.assertFalse(
            AuthorizationService.may_send_evidence_to_model(
                context,
                "production-shadow",
                {**identity, "target_hash": "b" * 64},
            )
        )

    def test_session_run_and_audit_enforce_object_owner(self) -> None:
        owner = self.context("reader-a")
        other = self.context("reader-b")
        result = self.service.query(self.query(), owner)
        with self.assertRaisesRegex(PermissionError, "owner scope"):
            self.service.audit(result["audit"]["audit_id"], other)

        assistant = AssistantService(
            self.service,
            self.root / "assistant",
            provider=FakeProvider(),
            default_access_context=owner,
        )
        session = assistant.create_session()
        run = assistant.message(
            session["session_id"], AssistantMessageRequest(message="查询进站客流")
        )
        with self.assertRaisesRegex(PermissionError, "owner scope"):
            assistant.get_run(run["run_id"], other)

    def test_global_rank_requeries_full_scope_and_incomplete_derivations_fail(self) -> None:
        context = self.context("reader-a")
        registry = ToolRegistry(self.service, self.root / "reports")
        query = registry.execute(
            "s1", "query_metric", self.query(limit=1).model_dump(mode="json"), [], context
        )
        self.assertTrue(query.truncated)
        ranked = registry.execute(
            "s2", "rank_stations", {"metric": "entries", "top_n": 1}, [query], context
        )
        self.assertEqual(ranked.status, "success")
        self.assertTrue(ranked.complete)
        self.assertFalse(ranked.truncated)
        self.assertEqual(ranked.matched_row_count, 2)
        self.assertEqual(ranked.calculation_method, "full_scope_group_order_limit")

        incomplete = ToolResult(
            step_id="source",
            tool="query_metric",
            status="success",
            rows=[{"station": "S-X", "entries": 1}],
            complete=False,
            truncated=True,
        )
        growth = registry.execute("s3", "calculate_growth", {}, [incomplete], context)
        self.assertEqual(growth.error_code, "incomplete_dependency")

    def test_comparison_requires_explicit_period_pair(self) -> None:
        context = self.context("reader-a")
        registry = ToolRegistry(self.service, self.root / "reports")
        result = registry.execute(
            "s1",
            "compare_metric_periods",
            self.query().model_dump(mode="json"),
            [],
            context,
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("explicit baseline", result.block_reason)

    def test_synthetic_and_shadow_backends_share_result_metadata_contract(self) -> None:
        synthetic = self.service.query(self.query(), self.context("reader-a"))
        settings = shadow_settings(self.root)
        shadow = MetroflowReadOnlyDataService(
            settings, StubDatabase(), ProductionSourcePolicy.from_settings(settings)
        ).query(shadow_query(), settings.access_context())
        required = {
            "metric_id",
            "metric_version",
            "metric_unit",
            "aggregation",
            "missing_value_policy",
            "city",
            "dataset_role",
            "source_version",
            "time_grain",
            "quality_status",
            "truncated",
            "complete",
            "returned_row_count",
            "matched_row_count",
            "query_fingerprint",
            "policy_snapshot_id",
            "access_scope_hash",
        }
        self.assertTrue(required.issubset(synthetic["provenance"]))
        self.assertTrue(required.issubset(shadow["provenance"]))
        self.assertEqual(synthetic["provenance"]["metric_unit"], "passengers")
        self.assertEqual(shadow["provenance"]["metric_unit"], "passengers")
        self.assertEqual(set(synthetic["rows"][0]), set(shadow["rows"][0]))

    def test_unimplemented_query_ir_time_semantics_are_rejected(self) -> None:
        cases = [
            {"time_grain": "day"},
            {
                "time_basis": "service_day",
                "service_day": "1999-01-01",
                "calendar_version": "missing-calendar",
            },
            {"data_as_of": "2000-01-01T00:00:00+08:00"},
            {"cross_midnight_policy": "service_day_calendar"},
        ]
        for update in cases:
            with self.subTest(update=update):
                request = QueryRequest.model_validate(
                    {**self.query().model_dump(mode="json"), **update}
                )
                with self.assertRaises(ValueError):
                    self.service.query(request, self.context("reader-a"))

    def test_synthetic_forecast_projects_only_authorized_metric_columns(self) -> None:
        context = self.context("reader-a").model_copy(
            update={"allowed_dataset_roles": ("forecast",)}
        )
        result = self.service.forecast(
            ForecastRequest(
                reference_date="2026-07-20",
                target_date="2026-07-21",
                scheme_id=1,
                limit=100,
            ),
            context,
        )
        self.assertIn("entries", result["rows"][0])
        self.assertNotIn("exits", result["rows"][0])
        self.assertNotIn("transfers", result["rows"][0])


if __name__ == "__main__":
    unittest.main()
