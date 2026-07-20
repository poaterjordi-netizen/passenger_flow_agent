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
        serialized = json.dumps(schema)
        self.assertNotIn("arbitrary-sql", serialized)
        self.assertEqual(self.endpoint("/health", "GET")()["data_scope"], "synthetic")
        self.assertEqual(self.endpoint("/", "GET")()["docs"], "/docs")

    def test_route_functions_delegate_to_synthetic_service(self) -> None:
        service = self.app.state.service
        catalog = self.endpoint("/api/v1/catalog", "GET")(service=service)
        self.assertEqual(catalog["lines"], ["L-A"])
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
        self.assertEqual(forecast_result["row_count"], 6)
        audit = self.endpoint("/api/v1/audits/{audit_id}", "GET")(
            audit_id=query_result["audit"]["audit_id"], service=service
        )
        self.assertEqual(audit["operation"], "query")
        with self.assertRaises(HTTPException) as raised:
            self.endpoint("/api/v1/audits/{audit_id}", "GET")(
                audit_id="query-" + "0" * 32, service=service
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_access_token_is_optional_and_constant_time_checked(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))
        self.assertIsNone(_authorize(request, None))

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
        self.assertIsNone(
            _authorize(
                protected,
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="expected"),
            )
        )
        with self.assertRaises(HTTPException) as raised:
            _authorize(protected, None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_value_error_handler_returns_redacted_shape(self) -> None:
        handler = self.app.exception_handlers[ValueError]
        response = asyncio.run(handler(None, ValueError("bad query")))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(json.loads(response.body)["error"]["code"], "invalid_request")

    def test_cors_is_opt_in(self) -> None:
        cors_settings = ApiSettings(
            metrics_path=self.settings.metrics_path,
            data_path=self.settings.data_path,
            audit_dir=Path(self.temporary.name) / "cors-audits",
            cors_origins=("https://example.test",),
        )
        application = create_app(cors_settings)
        self.assertTrue(any(middleware.cls.__name__ == "CORSMiddleware" for middleware in application.user_middleware))


if __name__ == "__main__":
    unittest.main()
