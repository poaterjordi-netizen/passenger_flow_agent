from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pymysql

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_STATION_FLOW_ROWS = 50_000
_MAX_OD_FLOW_ROWS = 200_000
_MAX_FILTER_VALUES = 100
_QUERY_CAPABILITY = object()


@dataclass(frozen=True)
class DatabaseSettings:
    """Runtime-only database settings.

    The password is excluded from representations so exceptions and debug output do
    not accidentally disclose it. The project deliberately does not load `.env`
    files; callers must inject credentials through the process environment or a
    secret manager.
    """

    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str = "metroflow"
    connect_timeout: int = 8
    read_timeout: int = 30
    ssl_ca: str | None = None
    allow_insecure_tls: bool = False

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> DatabaseSettings:
        env = os.environ if environment is None else environment
        required = {
            "METRO_DB_HOST": env.get("METRO_DB_HOST", "").strip(),
            "METRO_DB_USER": env.get("METRO_DB_USER", "").strip(),
            "METRO_DB_PASSWORD": env.get("METRO_DB_PASSWORD", ""),
            "METRO_DB_NAME": env.get("METRO_DB_NAME", "").strip(),
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"missing database environment variables: {', '.join(missing)}")
        try:
            port = int(env.get("METRO_DB_PORT", "3306"))
            connect_timeout = int(env.get("METRO_DB_CONNECT_TIMEOUT", "8"))
            read_timeout = int(env.get("METRO_DB_READ_TIMEOUT", "30"))
        except ValueError as exc:
            raise ValueError("database port and timeouts must be integers") from exc
        if not 1 <= port <= 65_535:
            raise ValueError("METRO_DB_PORT must be between 1 and 65535")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("database timeouts must be positive")
        insecure_tls_value = env.get("METRO_DB_ALLOW_INSECURE_TLS", "false").strip().lower()
        if insecure_tls_value not in {"true", "false"}:
            raise ValueError("METRO_DB_ALLOW_INSECURE_TLS must be true or false")
        return cls(
            host=required["METRO_DB_HOST"],
            port=port,
            user=required["METRO_DB_USER"],
            password=required["METRO_DB_PASSWORD"],
            database=required["METRO_DB_NAME"],
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            ssl_ca=env.get("METRO_DB_SSL_CA") or None,
            allow_insecure_tls=insecure_tls_value == "true",
        )

    def connection_kwargs(self) -> dict[str, Any]:
        if self.ssl_ca:
            ssl: dict[str, Any] = {"ca": self.ssl_ca, "check_hostname": True}
            verify_cert = True
            verify_identity = True
        elif self.allow_insecure_tls:
            # Explicit non-production escape hatch. Encryption is required below,
            # but the server identity is not verified in this mode.
            ssl = {"check_hostname": False}
            verify_cert = False
            verify_identity = False
        else:
            raise ValueError(
                "METRO_DB_SSL_CA is required for verified TLS; "
                "METRO_DB_ALLOW_INSECURE_TLS=true is non-production only"
            )
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "write_timeout": self.connect_timeout,
            "autocommit": False,
            "cursorclass": pymysql.cursors.DictCursor,
            "ssl": ssl,
            "ssl_verify_cert": verify_cert,
            "ssl_verify_identity": verify_identity,
        }


@dataclass(frozen=True)
class _DatabaseQuery:
    dataset: str
    sql: str
    parameters: tuple[Any, ...]
    row_limit: int
    capability: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class DatabaseQueryResult:
    dataset: str
    rows: list[dict[str, Any]]
    sql_template: str
    parameter_count: int
    tls_cipher: str
    truncated: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _validated_values(values: Sequence[Any] | None, field_name: str) -> tuple[Any, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of values, not one string")
    cleaned = tuple(values)
    if len(cleaned) > _MAX_FILTER_VALUES:
        raise ValueError(f"{field_name} accepts at most {_MAX_FILTER_VALUES} values")
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in cleaned):
        raise ValueError(f"{field_name} values must be non-empty")
    return cleaned


def _validated_limit(limit: int, maximum: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


def _add_in_filter(
    predicates: list[str],
    parameters: list[Any],
    column: str,
    values: tuple[Any, ...],
) -> None:
    if not values:
        return
    placeholders = ", ".join("%s" for _ in values)
    predicates.append(f"{column} IN ({placeholders})")
    parameters.extend(values)


def compile_station_flow_query(
    service_date: date,
    *,
    station_ids: Sequence[str] | None = None,
    line_ids: Sequence[str] | None = None,
    limit: int = 5_000,
) -> _DatabaseQuery:
    if not isinstance(service_date, date) or isinstance(service_date, datetime):
        raise ValueError("service_date must be a date")
    station_values = _validated_values(station_ids, "station_ids")
    line_values = _validated_values(line_ids, "line_ids")
    row_limit = _validated_limit(limit, _MAX_STATION_FLOW_ROWS)
    predicates = ["Date = %s"]
    parameters: list[Any] = [service_date]
    _add_in_filter(predicates, parameters, "StationID", station_values)
    _add_in_filter(predicates, parameters, "LineID", line_values)
    sql = (
        "SELECT StationID, StationName, LineName, StartTime, EndTime, InFlow, OutFlow "
        "FROM clear_stationflow_day "
        f"WHERE {' AND '.join(predicates)} "
        "ORDER BY StartTime, StationID, LineName LIMIT %s"
    )
    parameters.append(row_limit + 1)
    return _DatabaseQuery("station_flow_day", sql, tuple(parameters), row_limit, _QUERY_CAPABILITY)


def compile_od_flow_query(
    start: datetime,
    end: datetime,
    *,
    origin_station_ids: Sequence[int] | None = None,
    destination_station_ids: Sequence[int] | None = None,
    limit: int = 50_000,
) -> _DatabaseQuery:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValueError("OD time range must contain datetimes with start before end")
    if start.utcoffset() is not None or end.utcoffset() is not None:
        raise ValueError("OD time range must use naive local datetimes")
    if start >= end:
        raise ValueError("OD time range must contain datetimes with start before end")
    origin_values = _validated_values(origin_station_ids, "origin_station_ids")
    destination_values = _validated_values(destination_station_ids, "destination_station_ids")
    row_limit = _validated_limit(limit, _MAX_OD_FLOW_ROWS)
    predicates = ["StartTime >= %s", "StartTime < %s"]
    parameters: list[Any] = [start, end]
    _add_in_filter(predicates, parameters, "`进站车站ID`", origin_values)
    _add_in_filter(predicates, parameters, "`出站车站ID`", destination_values)
    sql = (
        "SELECT `进站车站ID` AS OriginStationID, "
        "`出站车站ID` AS DestinationStationID, StartTime, "
        "PASGR_FLOW_QTTY AS PassengerFlow "
        "FROM Refer_ODFlow_day "
        f"WHERE {' AND '.join(predicates)} "
        "ORDER BY StartTime, `进站车站ID`, `出站车站ID` LIMIT %s"
    )
    parameters.append(row_limit + 1)
    return _DatabaseQuery("reference_od_flow", sql, tuple(parameters), row_limit, _QUERY_CAPABILITY)


class ReadOnlyMetroDatabase:
    """Small, fail-closed MySQL adapter with no DML/DDL or free-SQL surface."""

    def __init__(
        self,
        settings: DatabaseSettings,
        *,
        connector: Callable[..., Any] = pymysql.connect,
    ) -> None:
        self.settings = settings
        self._connector = connector

    def _execute(self, query: _DatabaseQuery) -> DatabaseQueryResult:
        if query.capability is not _QUERY_CAPABILITY:
            raise ValueError("query was not produced by an allowlisted repository route")
        connection = self._connector(**self.settings.connection_kwargs())
        primary_error = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                tls_row = cursor.fetchone()
                if isinstance(tls_row, dict):
                    tls_cipher = str(tls_row.get("Value") or "")
                else:
                    tls_cipher = str(tls_row[1] if tls_row and len(tls_row) > 1 else "")
                if not tls_cipher:
                    raise RuntimeError("database connection did not negotiate TLS")

                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute("START TRANSACTION READ ONLY")
                cursor.execute(query.sql, query.parameters)
                raw_rows = list(cursor.fetchall())
                truncated = len(raw_rows) > query.row_limit
                rows = [dict(row) for row in raw_rows[: query.row_limit]]
            return DatabaseQueryResult(
                dataset=query.dataset,
                rows=rows,
                sql_template=query.sql,
                parameter_count=len(query.parameters),
                tls_cipher=tls_cipher,
                truncated=truncated,
            )
        except BaseException:
            primary_error = True
            raise
        finally:
            self._cleanup_connection(connection, suppress_errors=primary_error)

    @staticmethod
    def _cleanup_connection(connection: Any, *, suppress_errors: bool) -> None:
        cleanup_error: Exception | None = None
        try:
            connection.rollback()
        except Exception as exc:  # Preserve an earlier query/TLS error if present.
            cleanup_error = exc
        try:
            connection.close()
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None and not suppress_errors:
            raise cleanup_error

    def fetch_station_flow_day(
        self,
        service_date: date,
        *,
        station_ids: Sequence[str] | None = None,
        line_ids: Sequence[str] | None = None,
        limit: int = 5_000,
    ) -> list[dict[str, Any]]:
        return self.query_station_flow_day(
            service_date,
            station_ids=station_ids,
            line_ids=line_ids,
            limit=limit,
        ).rows

    def query_station_flow_day(
        self,
        service_date: date,
        *,
        station_ids: Sequence[str] | None = None,
        line_ids: Sequence[str] | None = None,
        limit: int = 5_000,
    ) -> DatabaseQueryResult:
        query = compile_station_flow_query(
            service_date,
            station_ids=station_ids,
            line_ids=line_ids,
            limit=limit,
        )
        return self._execute(query)

    def fetch_od_flow_window(
        self,
        start: datetime,
        end: datetime,
        *,
        origin_station_ids: Sequence[int] | None = None,
        destination_station_ids: Sequence[int] | None = None,
        limit: int = 50_000,
    ) -> list[dict[str, Any]]:
        return self.query_od_flow_window(
            start,
            end,
            origin_station_ids=origin_station_ids,
            destination_station_ids=destination_station_ids,
            limit=limit,
        ).rows

    def query_od_flow_window(
        self,
        start: datetime,
        end: datetime,
        *,
        origin_station_ids: Sequence[int] | None = None,
        destination_station_ids: Sequence[int] | None = None,
        limit: int = 50_000,
    ) -> DatabaseQueryResult:
        query = compile_od_flow_query(
            start,
            end,
            origin_station_ids=origin_station_ids,
            destination_station_ids=destination_station_ids,
            limit=limit,
        )
        return self._execute(query)

    def list_tables(self, *, limit: int = 200) -> DatabaseQueryResult:
        row_limit = _validated_limit(limit, 1_000)
        query = _DatabaseQuery(
            "schema_tables",
            "SELECT TABLE_NAME AS TableName, TABLE_ROWS AS EstimatedRows "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME LIMIT %s",
            (self.settings.database, row_limit + 1),
            row_limit,
            _QUERY_CAPABILITY,
        )
        return self._execute(query)

    def describe_table(self, table: str) -> DatabaseQueryResult:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError("table must be a simple SQL identifier")
        row_limit = 1_000
        query = _DatabaseQuery(
            "schema_columns",
            "SELECT COLUMN_NAME AS ColumnName, DATA_TYPE AS DataType, "
            "IS_NULLABLE AS IsNullable, COLUMN_KEY AS ColumnKey "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION LIMIT %s",
            (self.settings.database, table, row_limit + 1),
            row_limit,
            _QUERY_CAPABILITY,
        )
        return self._execute(query)


def write_database_audit(
    path: Path,
    result: DatabaseQueryResult,
    *,
    operation: str,
) -> None:
    fingerprint_input = json.dumps(
        {
            "dataset": result.dataset,
            "sql_template": result.sql_template,
            "parameter_count": result.parameter_count,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "succeeded",
        "operation": operation,
        "dataset": result.dataset,
        "query_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        "sql_template": result.sql_template,
        "parameter_count": result.parameter_count,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "tls_active": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
