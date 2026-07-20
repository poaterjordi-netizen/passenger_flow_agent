import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

import pymysql

import metro_agent.cli as cli_module
from metro_agent.cli import _publish_database_artifacts, _safe_error_payload
from metro_agent.database import DatabaseQueryResult

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

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["metro-agent", *arguments]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            return cli_module.main(), stdout.getvalue(), stderr.getvalue()

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

    def test_database_query_requires_runtime_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            process = self.run_cli(
                "db-station-flow",
                "--date",
                "2023-09-27",
                "--output",
                str(output),
                "--audit",
                str(audit),
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("METRO_DB_PASSWORD", json.loads(process.stderr)["error"])
        self.assertFalse(output.exists())
        self.assertFalse(audit.exists())

    def test_forecast_command_requires_runtime_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "forecast.csv"
            audit = Path(directory) / "audit.json"
            process = self.run_cli(
                "forecast-designated-day",
                "--reference-date",
                "2023-09-27",
                "--target-date",
                "2024-09-29",
                "--scheme-id",
                "58",
                "--output",
                str(output),
                "--audit",
                str(audit),
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("METRO_DB_PASSWORD", json.loads(process.stderr)["error"])
        self.assertFalse(output.exists())
        self.assertFalse(audit.exists())

    def test_database_errors_are_redacted(self) -> None:
        error = pymysql.OperationalError(1045, "access denied for synthetic-user at db.internal")
        payload = json.dumps(_safe_error_payload(error))
        self.assertIn("database_error", payload)
        self.assertNotIn("synthetic-user", payload)
        self.assertNotIn("db.internal", payload)

    def test_publish_refuses_to_overwrite_old_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            output.write_text("old-output", encoding="utf-8")
            audit.write_text("old-audit", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                _publish_database_artifacts(
                    output,
                    audit,
                    [],
                    DatabaseQueryResult("dataset", [], "SELECT 1", 0, "cipher", False),
                    "test",
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "old-output")
            self.assertEqual(audit.read_text(encoding="utf-8"), "old-audit")

    def test_publish_failure_leaves_no_partial_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            result = DatabaseQueryResult("dataset", [], "SELECT 1", 0, "cipher", False)
            with mock.patch(
                "metro_agent.cli.write_database_audit", side_effect=OSError("audit failed")
            ):
                with self.assertRaisesRegex(OSError, "audit failed"):
                    _publish_database_artifacts(output, audit, [], result, "test")
            self.assertFalse(output.exists())
            self.assertFalse(audit.exists())

    def test_concurrent_audit_target_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            result = DatabaseQueryResult("dataset", [], "SELECT 1", 0, "cipher", False)
            real_link = os.link

            def race_safe_link(source, target):
                if Path(target) == audit:
                    audit.write_text("concurrent-audit", encoding="utf-8")
                    raise FileExistsError("concurrent target")
                return real_link(source, target)

            with mock.patch("metro_agent.cli.os.link", side_effect=race_safe_link):
                with self.assertRaises(FileExistsError):
                    _publish_database_artifacts(output, audit, [], result, "test")
            self.assertFalse(output.exists())
            self.assertEqual(audit.read_text(encoding="utf-8"), "concurrent-audit")

    def test_output_write_failure_leaves_no_partial_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            result = DatabaseQueryResult("dataset", [], "SELECT 1", 0, "cipher", False)
            with mock.patch("metro_agent.cli._write_rows", side_effect=OSError("output failed")):
                with self.assertRaisesRegex(OSError, "output failed"):
                    _publish_database_artifacts(output, audit, [], result, "test")
            self.assertFalse(output.exists())
            self.assertFalse(audit.exists())

    def test_database_station_command_publishes_bounded_artifacts(self) -> None:
        row = {
            "StationID": "101",
            "StationName": "Alpha",
            "LineName": "Line 1",
            "StartTime": datetime(2023, 9, 27, 6, 0),
            "EndTime": datetime(2023, 9, 27, 6, 30),
            "InFlow": 1,
            "OutFlow": 1,
        }
        result = DatabaseQueryResult("station_flow_day", [row], "SELECT fixed", 2, "cipher", False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.json"
            audit = Path(directory) / "audit.json"
            with (
                mock.patch("metro_agent.cli._database_settings", return_value=object()),
                mock.patch("metro_agent.cli.ReadOnlyMetroDatabase") as database_class,
            ):
                database_class.return_value.query_station_flow_day.return_value = result
                code, stdout, stderr = self.run_main(
                    "db-station-flow",
                    "--date",
                    "2023-09-27",
                    "--output",
                    str(output),
                    "--audit",
                    str(audit),
                )
            self.assertEqual(code, 0, stderr)
            self.assertFalse(json.loads(stdout)["truncated"])
            self.assertTrue(output.exists())
            self.assertFalse(json.loads(audit.read_text(encoding="utf-8"))["truncated"])

    def test_database_metadata_commands_publish_artifacts(self) -> None:
        result = DatabaseQueryResult(
            "schema_tables", [{"TableName": "synthetic"}], "SELECT fixed", 2, "cipher", False
        )
        for command, extra in (("db-tables", []), ("db-describe", ["--table", "synthetic"])):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "rows.json"
                audit = Path(directory) / "audit.json"
                with (
                    mock.patch("metro_agent.cli._database_settings", return_value=object()),
                    mock.patch("metro_agent.cli.ReadOnlyMetroDatabase") as database_class,
                ):
                    database_class.return_value.list_tables.return_value = result
                    database_class.return_value.describe_table.return_value = result
                    code, _, stderr = self.run_main(
                        command,
                        *extra,
                        "--output",
                        str(output),
                        "--audit",
                        str(audit),
                    )
                self.assertEqual(code, 0, stderr)
                self.assertTrue(output.exists())
                self.assertTrue(audit.exists())

    def test_forecast_command_publishes_transformed_artifact(self) -> None:
        row = {
            "StationID": "101",
            "StationName": "Alpha",
            "LineName": "Line 1",
            "StartTime": datetime(2023, 9, 27, 23, 50),
            "EndTime": datetime(2023, 9, 27, 0, 10),
            "InFlow": 1,
            "OutFlow": 1,
        }
        result = DatabaseQueryResult("station_flow_day", [row], "SELECT fixed", 2, "cipher", False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "forecast.csv"
            audit = Path(directory) / "audit.json"
            with (
                mock.patch("metro_agent.cli._database_settings", return_value=object()),
                mock.patch("metro_agent.cli.ReadOnlyMetroDatabase") as database_class,
            ):
                database_class.return_value.query_station_flow_day.return_value = result
                code, _, stderr = self.run_main(
                    "forecast-designated-day",
                    "--reference-date",
                    "2023-09-27",
                    "--target-date",
                    "2024-02-29",
                    "--scheme-id",
                    "58",
                    "--output",
                    str(output),
                    "--audit",
                    str(audit),
                )
            self.assertEqual(code, 0, stderr)
            self.assertIn("2024-03-01 00:10:00", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
