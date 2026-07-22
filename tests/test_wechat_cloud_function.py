from __future__ import annotations

import json
import os
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "infra" / "cloudbase" / "functions" / "metroAgentApi-nodejs" / "index.js"
DATA_DIR = ROOT / "examples" / "synthetic_data"
ASSISTANT_VIEW_TEST = (
    ROOT / "clients" / "wechat-miniprogram" / "tests" / "assistant-view.test.js"
)
ASSISTANT_SESSION_FAILURE_TEST = (
    ROOT / "clients" / "wechat-miniprogram" / "tests" / "assistant-session-failure.test.js"
)
SETTINGS_CONNECTION_TEST = (
    ROOT / "clients" / "wechat-miniprogram" / "tests" / "settings-connection.test.js"
)


def invoke(
    events: list[dict[str, object]],
    *,
    extra_environment: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    script = """
const handler = require(process.argv[1]);
const events = JSON.parse(process.argv[2]);
Promise.all(events.map((event) => handler.main(event, {})))
  .then((results) => process.stdout.write(JSON.stringify(results)))
  .catch((error) => { console.error(error); process.exit(1); });
"""
    environment = os.environ.copy()
    environment["METRO_AGENT_DATA_DIR"] = str(DATA_DIR)
    environment.update(extra_environment or {})
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
    def test_assistant_view_formatter_matches_backend_trace_shape(self) -> None:
        result = subprocess.run(
            ["node", str(ASSISTANT_VIEW_TEST)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("assistant view formatter ok", result.stdout)

    def test_assistant_session_failure_keeps_actionable_backend_error(self) -> None:
        result = subprocess.run(
            ["node", str(ASSISTANT_SESSION_FAILURE_TEST)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("assistant session failure is actionable", result.stdout)

    def test_settings_checks_assistant_reachability_not_only_base_health(self) -> None:
        result = subprocess.run(
            ["node", str(SETTINGS_CONNECTION_TEST)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("settings detects unreachable assistant backend", result.stdout)

    def test_health_catalog_and_query_match_deterministic_baseline(self) -> None:
        health, catalog = invoke(
            [
                {"path": "/health", "method": "GET"},
                {"path": "/api/v1/catalog", "method": "GET"},
            ]
        )
        self.assertEqual(health["statusCode"], 200)
        self.assertEqual(health["data"]["data_scope"], "synthetic")
        self.assertFalse(health["data"]["assistant_proxy"]["configured"])
        self.assertFalse(health["data"]["assistant_proxy"]["reachable"])
        self.assertEqual(health["data"]["assistant_proxy"]["status"], "unconfigured")
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
        invalid, missing, assistant = invoke(
            [
                {"path": "/api/v1/queries", "method": "POST", "data": {}},
                {"path": "/missing", "method": "GET"},
                {"path": "/api/v1/assistant/capabilities", "method": "GET"},
            ]
        )
        self.assertEqual(invalid["statusCode"], 422)
        self.assertEqual(missing["statusCode"], 404)
        self.assertEqual(assistant["statusCode"], 503)
        self.assertEqual(
            assistant["data"]["error"]["code"], "assistant_backend_unconfigured"
        )

    def test_assistant_proxy_forwards_only_allowlisted_server_side_requests(self) -> None:
        received: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                payload = json.dumps(
                    {
                        "status": "ok",
                        "version": "0.4.1",
                        "environment": "test-live",
                        "data_scope": "production-shadow",
                    }
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                received.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("authorization"),
                        "body": body,
                    }
                )
                payload = json.dumps({"proxied": True, "path": self.path}).encode()
                self.send_response(201)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        session_id = "session-" + "a" * 32
        proxied, blocked = invoke(
            [
                {
                    "path": f"/api/v1/assistant/sessions/{session_id}/messages",
                    "method": "POST",
                    "data": {"message": "查询一号线"},
                },
                {
                    "path": "/api/v1/assistant/arbitrary",
                    "method": "POST",
                    "data": {},
                },
            ],
            extra_environment={
                "METRO_ASSISTANT_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "METRO_ASSISTANT_ALLOW_HTTP": "true",
                "METRO_ASSISTANT_API_ACCESS_TOKEN": "server-side-test-token",
            },
        )

        self.assertEqual(proxied["statusCode"], 201)
        self.assertTrue(proxied["data"]["proxied"])
        self.assertEqual(blocked["statusCode"], 404)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["authorization"], "Bearer server-side-test-token")
        self.assertEqual(received[0]["body"], {"message": "查询一号线"})

        health = invoke(
            [{"path": "/health", "method": "GET"}],
            extra_environment={
                "METRO_ASSISTANT_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "METRO_ASSISTANT_ALLOW_HTTP": "true",
                "METRO_ASSISTANT_API_ACCESS_TOKEN": "server-side-test-token",
            },
        )[0]
        self.assertTrue(health["data"]["assistant_proxy"]["reachable"])
        self.assertEqual(health["data"]["assistant_proxy"]["status"], "ready")
        self.assertEqual(health["data"]["assistant_proxy"]["upstream_version"], "0.4.1")


if __name__ == "__main__":
    unittest.main()
