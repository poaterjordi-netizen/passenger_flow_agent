import json
import tempfile
import unittest
from pathlib import Path

from metro_agent.query_engine import (
    compile_query,
    evaluate_gold_cases,
    execute_query,
    load_query_ir,
)

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "examples/synthetic_data/metrics.json"
GOLD_CASES = ROOT / "examples/synthetic_data/gold_cases.json"
DATA = ROOT / "examples/synthetic_data/passenger_flow.csv"


def entries_by_station_query() -> dict:
    return {
        "metric": "entries",
        "time_range": {
            "start": "2026-07-20T08:00:00+08:00",
            "end": "2026-07-20T09:00:00+08:00",
        },
        "dimensions": ["station"],
        "filters": [{"field": "line_id", "operator": "eq", "value": "L-A"}],
        "limit": 100,
    }


class QueryEngineTests(unittest.TestCase):
    def test_grouped_entries_match_gold_value(self) -> None:
        result = execute_query(METRICS, DATA, entries_by_station_query())
        self.assertEqual(result["status"], "answer")
        self.assertEqual(
            result["rows"],
            [
                {"station": "S-ALPHA", "entries": 200},
                {"station": "S-BETA", "entries": 125},
            ],
        )
        self.assertEqual(result["row_count"], 2)

    def test_all_registered_aggregates_are_deterministic(self) -> None:
        expected = {"entries": 325, "exits": 265, "transfers": 56, "net_inflow": 60}
        for metric, value in expected.items():
            with self.subTest(metric=metric):
                query = entries_by_station_query()
                query["metric"] = metric
                query["dimensions"] = []
                result = execute_query(METRICS, DATA, query)
                self.assertEqual(result["rows"], [{metric: value}])

    def test_filter_values_are_parameterized(self) -> None:
        query = entries_by_station_query()
        malicious_value = "L-A' OR 1=1 --"
        query["filters"][0]["value"] = malicious_value
        plan = compile_query(METRICS, query)
        self.assertNotIn(malicious_value, plan.sql)
        self.assertIn(malicious_value, plan.parameters)
        self.assertEqual(execute_query(METRICS, DATA, query)["rows"], [])

    def test_audit_artifact_records_template_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.json"
            result = execute_query(METRICS, DATA, entries_by_station_query(), audit_path=audit_path)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "succeeded")
        self.assertEqual(audit["row_count"], result["row_count"])
        self.assertIn("?", audit["sql_template"])
        self.assertNotIn("L-A", audit["sql_template"])
        self.assertEqual(audit["query_ir"], entries_by_station_query())

    def test_query_ir_file_loader_requires_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "root must be an object"):
                load_query_ir(path)

    def test_gold_case_evaluation_verifies_answer_and_policy_rejection(self) -> None:
        report = evaluate_gold_cases(METRICS, DATA, GOLD_CASES)
        self.assertEqual(report["summary"], {"total": 2, "passed": 2, "failed": 0})
        by_id = {case["case_id"]: case for case in report["cases"]}
        self.assertEqual(by_id["GC-001"]["actual_status"], "answer")
        self.assertTrue(by_id["GC-001"]["executed"])
        self.assertEqual(by_id["GC-002"]["actual_status"], "reject")
        self.assertFalse(by_id["GC-002"]["executed"])


if __name__ == "__main__":
    unittest.main()
