import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest import mock

import metro_agent.database as database_module
from metro_agent.database import (
    DatabaseSettings,
    ReadOnlyMetroDatabase,
    compile_od_flow_query,
    compile_station_flow_query,
)


class FakeCursor:
    def __init__(self, rows=None) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.description = None
        self._one: tuple[str, str] | None = None
        self._all = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, parameters=None):
        self.executions.append((sql, parameters))
        if sql.startswith("SHOW SESSION STATUS"):
            self._one = ("Ssl_cipher", "TLS_AES_256_GCM_SHA384")
        elif sql.startswith("SELECT StationID") and self._all is None:
            self._all = [
                {
                    "StationID": "101",
                    "StationName": "Alpha",
                    "LineName": "Line 1",
                    "StartTime": datetime(2023, 9, 27, 6, 0),
                    "EndTime": datetime(2023, 9, 27, 6, 30),
                    "InFlow": 12,
                    "OutFlow": 9,
                }
            ]
        return 1

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all or []


class FakeConnection:
    def __init__(self, rows=None, rollback_error=None) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.rollback_count = 0
        self.close_count = 0
        self.commit_count = 0
        self.rollback_error = rollback_error

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rollback_count += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def commit(self):
        self.commit_count += 1

    def close(self):
        self.close_count += 1


class DatabaseSettingsTests(unittest.TestCase):
    def test_from_env_requires_credentials_without_exposing_password(self) -> None:
        environment = {
            "METRO_DB_HOST": "db.internal",
            "METRO_DB_PORT": "3307",
            "METRO_DB_USER": "reader",
            "METRO_DB_PASSWORD": "top-secret",
            "METRO_DB_NAME": "metro",
        }
        settings = DatabaseSettings.from_env(environment)
        self.assertEqual(settings.port, 3307)
        self.assertNotIn("top-secret", repr(settings))

    def test_from_env_rejects_missing_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "METRO_DB_PASSWORD"):
            DatabaseSettings.from_env({"METRO_DB_HOST": "db"})

    def test_connection_requires_verified_ca_by_default(self) -> None:
        settings = DatabaseSettings("db", 3306, "reader", "secret", "metro")
        with self.assertRaisesRegex(ValueError, "METRO_DB_SSL_CA"):
            settings.connection_kwargs()

    def test_insecure_tls_requires_explicit_nonproduction_switch(self) -> None:
        environment = {
            "METRO_DB_HOST": "db.internal",
            "METRO_DB_USER": "reader",
            "METRO_DB_PASSWORD": "top-secret",
            "METRO_DB_NAME": "metro",
            "METRO_DB_ALLOW_INSECURE_TLS": "true",
        }
        settings = DatabaseSettings.from_env(environment)
        self.assertTrue(settings.allow_insecure_tls)
        self.assertFalse(settings.connection_kwargs()["ssl"]["check_hostname"])

    def test_verified_tls_enables_certificate_and_identity_checks(self) -> None:
        settings = DatabaseSettings(
            "db", 3306, "reader", "secret", "metro", ssl_ca="/path/to/ca.pem"
        )
        kwargs = settings.connection_kwargs()
        self.assertTrue(kwargs["ssl"]["check_hostname"])
        self.assertTrue(kwargs["ssl_verify_cert"])
        self.assertTrue(kwargs["ssl_verify_identity"])


class QueryCompilationTests(unittest.TestCase):
    def test_station_flow_values_are_parameterized(self) -> None:
        malicious = "101' OR 1=1 --"
        query = compile_station_flow_query(
            date(2023, 9, 27), station_ids=[malicious], line_ids=["1"], limit=50
        )
        self.assertNotIn(malicious, query.sql)
        self.assertIn(malicious, query.parameters)
        self.assertIn("Date = %s", query.sql)
        self.assertEqual(query.parameters[-1], 51)

    def test_od_window_is_half_open_and_parameterized(self) -> None:
        query = compile_od_flow_query(
            datetime(2022, 10, 17, 6, 0),
            datetime(2022, 10, 17, 6, 30),
            origin_station_ids=[101],
            limit=100,
        )
        self.assertIn("StartTime >= %s", query.sql)
        self.assertIn("StartTime < %s", query.sql)
        self.assertNotIn("2022-10-17", query.sql)

    def test_od_window_rejects_timezone_aware_datetimes(self) -> None:
        with self.assertRaisesRegex(ValueError, "naive local datetimes"):
            compile_od_flow_query(
                datetime(2022, 10, 17, 6, 0, tzinfo=UTC),
                datetime(2022, 10, 17, 6, 30, tzinfo=UTC),
            )

    def test_invalid_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            compile_station_flow_query(date(2023, 9, 27), limit=50001)
        self.assertEqual(
            compile_station_flow_query(date(2023, 9, 27), limit=50000).parameters[-1],
            50001,
        )

    def test_one_string_is_not_misread_as_many_station_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            compile_station_flow_query(date(2023, 9, 27), station_ids="101")


class ReadOnlyExecutionTests(unittest.TestCase):
    def settings(self) -> DatabaseSettings:
        return DatabaseSettings(
            host="db.internal",
            port=3306,
            user="reader",
            password="secret",
            database="metro",
            allow_insecure_tls=True,
        )

    def test_executor_requires_tls_and_read_only_transaction(self) -> None:
        connection = FakeConnection()
        connector = mock.Mock(return_value=connection)
        database = ReadOnlyMetroDatabase(self.settings(), connector=connector)
        rows = database.fetch_station_flow_day(date(2023, 9, 27), limit=10)
        sql_statements = [item[0] for item in connection.cursor_instance.executions]

        self.assertFalse(hasattr(database, "execute"))
        self.assertFalse(hasattr(database_module, "DatabaseQuery"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(sql_statements[0], "SHOW SESSION STATUS LIKE 'Ssl_cipher'")
        self.assertIn("SET SESSION TRANSACTION READ ONLY", sql_statements)
        self.assertIn("START TRANSACTION READ ONLY", sql_statements)
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.close_count, 1)

    def test_forged_sql_cannot_reach_the_connector(self) -> None:
        connector = mock.Mock()
        database = ReadOnlyMetroDatabase(self.settings(), connector=connector)
        legitimate = compile_station_flow_query(date(2023, 9, 27), limit=1)
        for statement in (
            "DROP TABLE protected",
            "INSERT INTO protected VALUES (1)",
            "CALL mutate_data()",
            "SET autocommit = 1",
            "COMMIT",
        ):
            forged = type(legitimate)("forged", statement, (), 1, object())
            with (
                self.subTest(statement=statement),
                self.assertRaisesRegex(ValueError, "allowlisted repository route"),
            ):
                database._execute(forged)
        connector.assert_not_called()

    def test_executor_rejects_connection_without_tls(self) -> None:
        connection = FakeConnection()

        def execute_without_tls(sql, parameters=None):
            connection.cursor_instance.executions.append((sql, parameters))
            if sql.startswith("SHOW SESSION STATUS"):
                connection.cursor_instance._one = ("Ssl_cipher", "")
            return 1

        connection.cursor_instance.execute = execute_without_tls
        database = ReadOnlyMetroDatabase(self.settings(), connector=lambda **_: connection)
        with self.assertRaisesRegex(RuntimeError, "TLS"):
            database.fetch_station_flow_day(date(2023, 9, 27), limit=10)
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_limit_plus_one_distinguishes_complete_and_truncated_results(self) -> None:
        base_row = {
            "StationID": "101",
            "StationName": "Alpha",
            "LineName": "Line 1",
            "StartTime": datetime(2023, 9, 27, 6, 0),
            "EndTime": datetime(2023, 9, 27, 6, 30),
            "InFlow": 1,
            "OutFlow": 1,
        }
        complete = ReadOnlyMetroDatabase(
            self.settings(), connector=lambda **_: FakeConnection([dict(base_row), dict(base_row)])
        ).query_station_flow_day(date(2023, 9, 27), limit=2)
        below_limit = ReadOnlyMetroDatabase(
            self.settings(), connector=lambda **_: FakeConnection([dict(base_row)])
        ).query_station_flow_day(date(2023, 9, 27), limit=2)
        truncated = ReadOnlyMetroDatabase(
            self.settings(),
            connector=lambda **_: FakeConnection([dict(base_row), dict(base_row), dict(base_row)]),
        ).query_station_flow_day(date(2023, 9, 27), limit=2)
        self.assertFalse(below_limit.truncated)
        self.assertEqual(below_limit.row_count, 1)
        self.assertFalse(complete.truncated)
        self.assertEqual(complete.row_count, 2)
        self.assertTrue(truncated.truncated)
        self.assertEqual(truncated.row_count, 2)

    def test_rollback_failure_still_closes_and_preserves_primary_error(self) -> None:
        connection = FakeConnection(rollback_error=RuntimeError("rollback failed"))

        def execute_without_tls(sql, parameters=None):
            connection.cursor_instance.executions.append((sql, parameters))
            if sql.startswith("SHOW SESSION STATUS"):
                connection.cursor_instance._one = ("Ssl_cipher", "")
            return 1

        connection.cursor_instance.execute = execute_without_tls
        database = ReadOnlyMetroDatabase(self.settings(), connector=lambda **_: connection)
        with self.assertRaisesRegex(RuntimeError, "did not negotiate TLS"):
            database.fetch_station_flow_day(date(2023, 9, 27), limit=10)
        self.assertEqual(connection.close_count, 1)


if __name__ == "__main__":
    unittest.main()
