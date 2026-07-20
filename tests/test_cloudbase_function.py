from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "infra" / "cloudbase" / "functions" / "metroAgentApi" / "index.py"


def _load_handler():
    spec = importlib.util.spec_from_file_location("metro_agent_cloudbase_handler", HANDLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("CloudBase handler could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CloudBaseFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.handler = _load_handler()

    def test_health_and_catalog_routes(self) -> None:
        health = self.handler.main({"path": "/health", "method": "GET"}, None)
        catalog = self.handler.main({"path": "/api/v1/catalog", "method": "GET"}, None)

        self.assertEqual(health["statusCode"], 200)
        self.assertEqual(health["data"]["data_scope"], "synthetic")
        self.assertEqual(catalog["statusCode"], 200)
        self.assertEqual(len(catalog["data"]["metrics"]), 4)

    def test_query_returns_retrievable_redacted_audit(self) -> None:
        catalog = self.handler.main({"path": "/api/v1/catalog", "method": "GET"}, None)
        query = self.handler.main(
            {
                "path": "/api/v1/queries",
                "method": "POST",
                "data": {
                    "metric": "entries",
                    "time_range": catalog["data"]["default_time_range"],
                    "dimensions": ["station"],
                    "filters": [],
                    "limit": 100,
                },
            },
            None,
        )

        self.assertEqual(query["statusCode"], 200)
        audit_id = query["data"]["audit"]["audit_id"]
        audit = self.handler.main({"path": f"/api/v1/audits/{audit_id}", "method": "GET"}, None)
        self.assertEqual(audit["statusCode"], 200)
        self.assertNotIn("query_ir", audit["data"])

    def test_invalid_payload_and_unknown_route_are_rejected(self) -> None:
        invalid = self.handler.main({"path": "/api/v1/queries", "method": "POST", "data": {}}, None)
        missing = self.handler.main({"path": "/missing", "method": "GET"}, None)

        self.assertEqual(invalid["statusCode"], 422)
        self.assertEqual(missing["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
