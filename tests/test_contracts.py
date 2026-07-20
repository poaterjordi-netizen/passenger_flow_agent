import json
import tempfile
import unittest
from pathlib import Path

from metro_agent.contracts import validate_query_ir, validate_repository_contracts

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "examples/synthetic_data/metrics.json"
GOLD_CASES = ROOT / "examples/synthetic_data/gold_cases.json"
DATA = ROOT / "examples/synthetic_data/passenger_flow.csv"


class ContractTests(unittest.TestCase):
    def test_repository_fixtures_validate(self) -> None:
        self.assertEqual(
            validate_repository_contracts(METRICS, GOLD_CASES, DATA),
            {"metrics": 4, "gold_cases": 2, "data_rows": 20},
        )

    def test_unknown_metric_fails_closed(self) -> None:
        registry = {"entries": {"dimensions": ["station"]}}
        query = {
            "metric": "invented_metric",
            "time_range": {
                "start": "2026-07-20T08:00:00+08:00",
                "end": "2026-07-20T09:00:00+08:00",
            },
            "dimensions": [],
            "filters": [],
            "limit": 10,
        }
        with self.assertRaisesRegex(ValueError, "unknown metric"):
            validate_query_ir(query, registry, "test")

    def test_duplicate_gold_case_id_is_rejected(self) -> None:
        payload = json.loads(GOLD_CASES.read_text(encoding="utf-8"))
        payload["cases"].append(payload["cases"][0])
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "gold_cases.json"
            broken.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate case_id"):
                validate_repository_contracts(METRICS, broken, DATA)

    def test_empty_in_filter_fails_closed(self) -> None:
        registry = {"entries": {"dimensions": ["station"]}}
        query = {
            "metric": "entries",
            "time_range": {
                "start": "2026-07-20T08:00:00+08:00",
                "end": "2026-07-20T09:00:00+08:00",
            },
            "dimensions": [],
            "filters": [{"field": "line_id", "operator": "in", "value": []}],
            "limit": 10,
        }
        with self.assertRaisesRegex(ValueError, "1 to 100 non-empty strings"):
            validate_query_ir(query, registry, "test")

    def test_invalid_direction_filter_fails_closed(self) -> None:
        registry = {"entries": {"dimensions": ["direction"]}}
        query = {
            "metric": "entries",
            "time_range": {
                "start": "2026-07-20T08:00:00+08:00",
                "end": "2026-07-20T09:00:00+08:00",
            },
            "dimensions": [],
            "filters": [{"field": "direction", "operator": "eq", "value": "sideways"}],
            "limit": 10,
        }
        with self.assertRaisesRegex(ValueError, "invalid direction"):
            validate_query_ir(query, registry, "test")


if __name__ == "__main__":
    unittest.main()
