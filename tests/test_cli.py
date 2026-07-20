import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "examples/synthetic_data/metrics.json"
GOLD_CASES = ROOT / "examples/synthetic_data/gold_cases.json"
DATA = ROOT / "examples/synthetic_data/passenger_flow.csv"
QUERY = ROOT / "examples/query_ir/entries_by_station.json"


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        source_path = str(ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (source_path, environment.get("PYTHONPATH", "")) if part
        )
        return subprocess.run(
            [sys.executable, "-m", "metro_agent.cli", *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_query_command_writes_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "audit.json"
            process = self.run_cli(
                "query",
                "--metrics",
                str(METRICS),
                "--data",
                str(DATA),
                "--query-ir",
                str(QUERY),
                "--audit",
                str(audit),
            )
            payload = json.loads(process.stdout)
            audit_payload = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(audit_payload["status"], "succeeded")

    def test_eval_command_writes_passing_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "eval.json"
            process = self.run_cli(
                "eval",
                "--metrics",
                str(METRICS),
                "--data",
                str(DATA),
                "--gold-cases",
                str(GOLD_CASES),
                "--report",
                str(report),
            )
            summary = json.loads(process.stdout)
            report_payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(summary, {"failed": 0, "passed": 2, "total": 2})
        self.assertEqual(report_payload["summary"], summary)

    def test_invalid_query_returns_machine_readable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad_query = Path(directory) / "bad.json"
            audit = Path(directory) / "audit.json"
            bad_query.write_text("[]", encoding="utf-8")
            process = self.run_cli(
                "query",
                "--metrics",
                str(METRICS),
                "--data",
                str(DATA),
                "--query-ir",
                str(bad_query),
                "--audit",
                str(audit),
            )
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads(process.stderr)["status"], "error")
        self.assertFalse(audit.exists())


if __name__ == "__main__":
    unittest.main()
