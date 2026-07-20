from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "infra" / "cloudbase" / "functions" / "metroAgentApi-nodejs" / "index.js"
DATA_DIR = ROOT / "examples" / "synthetic_data"


def invoke(events: list[dict[str, object]]) -> list[dict[str, object]]:
    script = """
const handler = require(process.argv[1]);
const events = JSON.parse(process.argv[2]);
Promise.all(events.map((event) => handler.main(event, {})))
  .then((results) => process.stdout.write(JSON.stringify(results)))
  .catch((error) => { console.error(error); process.exit(1); });
"""
    environment = os.environ.copy()
    environment["METRO_AGENT_DATA_DIR"] = str(DATA_DIR)
    result = subprocess.run(
        ["node", "-e", script, str(HANDLER), json.dumps(events)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class WeChatCloudFunctionTests(unittest.TestCase):
    def test_health_catalog_and_query_match_deterministic_baseline(self) -> None:
        health, catalog = invoke(
            [
                {"path": "/health", "method": "GET"},
                {"path": "/api/v1/catalog", "method": "GET"},
            ]
        )
        self.assertEqual(health["statusCode"], 200)
        self.assertEqual(health["data"]["data_scope"], "synthetic")
        self.assertEqual(len(catalog["data"]["metrics"]), 4)

        query = invoke(
            [
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
                }
            ]
        )[0]
        self.assertEqual(query["statusCode"], 200)
        self.assertEqual(
            query["data"]["rows"],
            [
                {"station": "S-ALPHA", "entries": 871},
                {"station": "S-BETA", "entries": 676},
            ],
        )

    def test_forecast_copies_only_synthetic_reference_rows(self) -> None:
        forecast = invoke(
            [
                {
                    "path": "/api/v1/forecasts/designated-day",
                    "method": "POST",
                    "data": {
                        "reference_date": "2026-07-20",
                        "target_date": "2026-07-21",
                        "scheme_id": 2,
                        "limit": 1000,
                    },
                }
            ]
        )[0]
        self.assertEqual(forecast["statusCode"], 200)
        self.assertEqual(forecast["data"]["row_count"], 20)
        self.assertTrue(
            all(row["timestamp"].startswith("2026-07-21T") for row in forecast["data"]["rows"])
        )

    def test_invalid_query_and_unknown_route_are_rejected(self) -> None:
        invalid, missing = invoke(
            [
                {"path": "/api/v1/queries", "method": "POST", "data": {}},
                {"path": "/missing", "method": "GET"},
            ]
        )
        self.assertEqual(invalid["statusCode"], 422)
        self.assertEqual(missing["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
