import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from metro_agent.api.app import _authorize, create_app
from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.settings import ApiSettings
from metro_agent.assistant.schemas import AssistantMessageRequest, HumanFeedbackRequest

ROOT = Path(__file__).resolve().parents[1]


class ApiApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = ApiSettings(
            metrics_path=ROOT / "examples/synthetic_data/metrics.json",
            data_path=ROOT / "examples/synthetic_data/passenger_flow.csv",
            audit_dir=Path(self.temporary.name) / "audits",
            environment="test",
        )
        self.app = create_app(self.settings)

    def endpoint(self, path: str, method: str):
        routes = list(self.app.routes)
        for included in self.app.routes:
            original_router = getattr(included, "original_router", None)
            if original_router is not None:
                routes.extend(original_router.routes)
        for route in routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        self.fail(f"missing {method} {path}")

    def test_openapi_exposes_only_bounded_mobile_routes(self) -> None:
        schema = self.app.openapi()
        self.assertIn("/api/v1/queries", schema["paths"])
        self.assertIn("/api/v1/forecasts/designated-day", schema["paths"])
        self.assertIn("/api/v1/assistant/sessions", schema["paths"])
        self.assertIn("/api/v1/assistant/capabilities", schema["paths"])
        self.assertIn("/api/v1/governance/status", schema["paths"])
        self.assertIn("/api/v1/assistant/sessions/{session_id}/messages", schema["paths"])
        self.assertIn("/api/v1/assistant/runs/{run_id}", schema["paths"])
        self.assertIn("/api/v1/assistant/runs/{run_id}/events", schema["paths"])
        self.assertIn("/api/v1/assistant/runs/{run_id}/feedback", schema["paths"])
        serialized = json.dumps(schema)
        self.assertNotIn("arbitrary-sql", serialized)
        self.assertEqual(self.endpoint("/health", "GET")()["data_scope"], "synthetic")
        self.assertEqual(self.endpoint("/", "GET")()["docs"], "/docs")

        capabilities = self.endpoint("/api/v1/assistant/capabilities", "GET")(
            assistant=self.app.state.assistant
        )
        self.assertEqual(capabilities["implementation_status"], "local_governed_prototype")
        self.assertEqual(capabilities["active_runtime"]["provider"], "fake-governed")
        self.assertEqual(capabilities["active_runtime"]["mode"], "offline_deterministic")
        self.assertFalse(capabilities["active_runtime"]["real_model_configured"])
        self.assertFalse(capabilities["active_runtime"]["real_model_active"])
        self.assertEqual(capabilities["active_runtime"]["invocation_status"], "not_applicable")
        self.assertEqual(capabilities["validated_milestones"][0]["evidence"], "100/100")
        self.assertEqual(capabilities["validated_milestones"][1]["evidence"], "3/3")

        governance = self.endpoint("/api/v1/governance/status", "GET")(
            service=self.app.state.service,
            assistant=self.app.state.assistant,
        )
        self.assertTrue(governance["assistant_enabled"])
        self.assertEqual(governance["assistant_status"], "synthetic_baseline")
        self.assertEqual(governance["identity"]["subject_id"], "local-synthetic-user")
        self.assertEqual(governance["access_scope"]["row_limit"], 1000)
        self.assertEqual(governance["data_source"]["source_version"], "synthetic-v1")
        self.assertEqual(governance["model_policy"]["data_egress"], "synthetic-only")
        self.assertTrue(governance["model_policy"]["evidence_egress_allowed"])
        self.assertEqual(
            governance["tool_registry"]["tool_count"],
            len(governance["tool_registry"]["registered_tools"]),
        )
        self.assertFalse(governance["promotion"]["ready"])
        self.assertFalse(governance["promotion"]["enforced"])

    def test_route_functions_delegate_to_synthetic_service(self) -> None:
        service = self.app.state.service
        catalog = self.endpoint("/api/v1/catalog", "GET")(service=service)
        self.assertEqual(catalog["lines"], ["L-A", "L-B"])
        query_result = self.endpoint("/api/v1/queries", "POST")(
            payload=QueryRequest.model_validate(
                {
                    "metric": "entries",
                    "time_range": {
                        "start": "2026-07-20T08:00:00+08:00",
                        "end": "2026-07-20T10:00:00+08:00",
                    },
                    "dimensions": [],
                    "filters": [],
                    "limit": 10,
                }
            ),
            service=service,
        )
        self.assertEqual(query_result["row_count"], 1)
        forecast_result = self.endpoint("/api/v1/forecasts/designated-day", "POST")(
            payload=ForecastRequest.model_validate(
                {
                    "reference_date": "2026-07-20",
                    "target_date": "2026-07-21",
                    "scheme_id": 2,
                    "limit": 100,
                }
            ),
            service=service,
        )
        self.assertEqual(forecast_result["row_count"], 20)
        audit = self.endpoint("/api/v1/audits/{audit_id}", "GET")(
            audit_id=query_result["audit"]["audit_id"], service=service
        )
        self.assertEqual(audit["operation"], "query")
        with self.assertRaises(HTTPException) as raised:
            self.endpoint("/api/v1/audits/{audit_id}", "GET")(
                audit_id="query-" + "0" * 32, service=service
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_assistant_routes_complete_and_replay_a_run(self) -> None:
        assistant = self.app.state.assistant
        session = self.endpoint("/api/v1/assistant/sessions", "POST")(assistant=assistant)
        run = self.endpoint("/api/v1/assistant/sessions/{session_id}/messages", "POST")(
            payload=AssistantMessageRequest(message="查询各站进站客流"),
            session_id=session["session_id"],
            assistant=assistant,
        )
        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["verification"]["valid"])
        self.assertEqual(run["model_runtime"]["provider_calls"], 0)
        self.assertEqual(run["model_runtime"]["model_calls"], 0)
        self.assertEqual(run["model_runtime"]["usage_reporting"], "not_applicable")
        self.assertIsNone(run["model_runtime"]["model"])
        replay = self.endpoint("/api/v1/assistant/runs/{run_id}", "GET")(
            run_id=run["run_id"], assistant=assistant
        )
        events = self.endpoint("/api/v1/assistant/runs/{run_id}/events", "GET")(
            run_id=run["run_id"], assistant=assistant
        )
        self.assertEqual(replay["run_id"], run["run_id"])
        self.assertEqual(events[-1]["state"], "RESPOND")
        feedback = self.endpoint("/api/v1/assistant/runs/{run_id}/feedback", "POST")(
            payload=HumanFeedbackRequest(
                correction="人工复核后采纳",
                accepted=True,
                adopted_response=run["response"],
            ),
            run_id=run["run_id"],
            assistant=assistant,
        )
        self.assertTrue(feedback["dataset_eligibility"]["eligible"])
        self.assertEqual(feedback["events"][-1]["state"], "HUMAN_FEEDBACK")

    def test_access_token_is_optional_and_constant_time_checked(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=self.settings))
        )
        self.assertEqual(_authorize(request, None).subject_id, "local-synthetic-user")

        protected = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    settings=ApiSettings(
                        metrics_path=self.settings.metrics_path,
                        data_path=self.settings.data_path,
                        audit_dir=self.settings.audit_dir,
                        access_token="expected",
                    )
                )
            )
        )
        self.assertEqual(
            _authorize(
                protected,
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="expected"),
            ).subject_id,
            "local-synthetic-user",
        )
        with self.assertRaises(HTTPException) as raised:
            _authorize(protected, None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_value_error_handler_returns_redacted_shape(self) -> None:
        handler = self.app.exception_handlers[ValueError]
        response = asyncio.run(handler(None, ValueError("secret backend path /tmp/private")))
        self.assertEqual(response.status_code, 422)
        payload = json.loads(response.body)
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "request failed validation")
        self.assertNotIn("private", response.body.decode())

    def test_runtime_error_handler_returns_redacted_provider_failure(self) -> None:
        handler = self.app.exception_handlers[RuntimeError]
        response = asyncio.run(handler(None, RuntimeError("token=secret-internal-detail")))
        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.body)
        self.assertEqual(payload["error"]["code"], "provider_failure")
        self.assertNotIn("secret", response.body.decode())

    def test_cors_is_opt_in(self) -> None:
        cors_settings = ApiSettings(
            metrics_path=self.settings.metrics_path,
            data_path=self.settings.data_path,
            audit_dir=Path(self.temporary.name) / "cors-audits",
            cors_origins=("https://example.test",),
        )
        application = create_app(cors_settings)
        self.assertTrue(
            any(
                middleware.cls.__name__ == "CORSMiddleware"
                for middleware in application.user_middleware
            )
        )


if __name__ == "__main__":
    unittest.main()
