import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from metro_agent.api.models import ForecastRequest, QueryRequest
from metro_agent.api.service import AuditStore, SyntheticApiService
from metro_agent.api.settings import ApiSettings

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "examples/synthetic_data/metrics.json"
DATA = ROOT / "examples/synthetic_data/passenger_flow.csv"


def _settings(audit_dir: Path, **overrides) -> ApiSettings:
    values = {
        "metrics_path": METRICS,
        "data_path": DATA,
        "audit_dir": audit_dir,
        "environment": "test",
    }
    values.update(overrides)
    return ApiSettings(**values)


class ApiSettingsTests(unittest.TestCase):
    def test_environment_settings_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ApiSettings.from_env(
                {
                    "METRO_AGENT_ROOT": str(ROOT),
                    "METRO_AGENT_DATA_DIR": str(ROOT / "examples/synthetic_data"),
                    "METRO_API_AUDIT_DIR": str(root / "audits"),
                    "METRO_API_ACCESS_TOKEN": " token ",
                    "METRO_API_CORS_ORIGINS": "https://one.test, https://two.test",
                }
            )
        self.assertEqual(settings.metrics_path, METRICS)
        self.assertEqual(settings.data_path, DATA)
        self.assertEqual(settings.access_token, "token")
        self.assertEqual(settings.cors_origins, ("https://one.test", "https://two.test"))


class AuditStoreTests(unittest.TestCase):
    def test_store_round_trip_and_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AuditStore(Path(directory))
            record = store.write(
                "query",
                {
                    "query_fingerprint": "f" * 64,
                    "row_count": 1,
                    "data_source": "synthetic.csv",
                },
            )
            self.assertEqual(store.get(record["audit_id"]), record)
            with self.assertRaisesRegex(ValueError, "invalid audit id"):
                store.get("../secret")
            with self.assertRaises(FileNotFoundError):
                store.get("query-" + "0" * 32)
            with self.assertRaisesRegex(ValueError, "unsupported"):
                store.write("delete", {})

    def test_corrupt_audit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AuditStore(Path(directory))
            audit_id = "query-" + "a" * 32
            (Path(directory) / f"{audit_id}.json").write_text(
                json.dumps({"audit_id": "query-" + "b" * 32}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "invalid audit record"):
                store.get(audit_id)


class SyntheticApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = SyntheticApiService(_settings(Path(self.temporary.name) / "audits"))

    def test_catalog_is_derived_from_contract_fixtures(self) -> None:
        catalog = self.service.catalog()
        self.assertEqual(catalog["data_scope"], "synthetic")
        self.assertEqual([row["id"] for row in catalog["metrics"]], [
            "entries", "exits", "transfers", "net_inflow"
        ])
        self.assertEqual(catalog["lines"], ["L-A"])
        self.assertEqual(catalog["stations"], ["S-ALPHA", "S-BETA"])
        self.assertEqual(catalog["available_dates"], ["2026-07-20"])
        self.assertEqual(catalog["default_time_range"]["end"], "2026-07-20T10:00:00+08:00")

    def test_query_executes_and_writes_retrievable_audit(self) -> None:
        result = self.service.query(
            QueryRequest.model_validate(
                {
                    "metric": "entries",
                    "time_range": {
                        "start": "2026-07-20T08:00:00+08:00",
                        "end": "2026-07-20T10:00:00+08:00",
                    },
                    "dimensions": ["station"],
                    "filters": [],
                    "limit": 100,
                }
            )
        )
        self.assertEqual(result["rows"], [
            {"station": "S-ALPHA", "entries": 375},
            {"station": "S-BETA", "entries": 125},
        ])
        audit = self.service.audit(result["audit"]["audit_id"])
        self.assertEqual(audit["operation"], "query")
        self.assertEqual(audit["row_count"], 2)
        self.assertNotIn("query_ir", audit)

    def test_query_reuses_existing_fail_closed_validation(self) -> None:
        request = QueryRequest.model_validate(
            {
                "metric": "invented",
                "time_range": {
                    "start": "2026-07-20T08:00:00+08:00",
                    "end": "2026-07-20T10:00:00+08:00",
                },
                "dimensions": [],
                "filters": [],
                "limit": 10,
            }
        )
        with self.assertRaisesRegex(ValueError, "unknown metric"):
            self.service.query(request)

    def test_forecast_copies_reference_pattern_without_writes(self) -> None:
        result = self.service.forecast(
            ForecastRequest(
                reference_date=date(2026, 7, 20),
                target_date=date(2026, 7, 21),
                scheme_id=7,
                limit=1000,
            )
        )
        self.assertEqual(result["method"], "reference_day_copy")
        self.assertEqual(result["row_count"], 6)
        self.assertTrue(all(row["timestamp"].startswith("2026-07-21T") for row in result["rows"]))
        self.assertTrue(all(row["scheme_id"] == 7 for row in result["rows"]))
        self.assertEqual(self.service.audit(result["audit"]["audit_id"])["operation"], "forecast")

    def test_forecast_rejects_missing_reference_and_truncation(self) -> None:
        with self.assertRaisesRegex(ValueError, "no synthetic rows"):
            self.service.forecast(
                ForecastRequest(
                    reference_date=date(2026, 7, 19),
                    target_date=date(2026, 7, 21),
                    scheme_id=1,
                )
            )
        with self.assertRaisesRegex(ValueError, "row limit"):
            self.service.forecast(
                ForecastRequest(
                    reference_date=date(2026, 7, 20),
                    target_date=date(2026, 7, 21),
                    scheme_id=1,
                    limit=2,
                )
            )


if __name__ == "__main__":
    unittest.main()
