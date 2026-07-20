from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pymysql

from metro_agent.contracts import validate_repository_contracts
from metro_agent.database import (
    DatabaseQueryResult,
    DatabaseSettings,
    ReadOnlyMetroDatabase,
    write_database_audit,
)
from metro_agent.forecasting import transform_designated_day_flow
from metro_agent.query_engine import (
    evaluate_gold_cases,
    execute_query,
    load_query_ir,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metro-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate", help="validate P0 contracts and synthetic fixtures"
    )
    validate.add_argument("--metrics", type=Path, required=True)
    validate.add_argument("--gold-cases", type=Path, required=True)
    validate.add_argument("--data", type=Path, required=True)
    query = subparsers.add_parser("query", help="execute a validated QueryIR on synthetic data")
    query.add_argument("--metrics", type=Path, required=True)
    query.add_argument("--data", type=Path, required=True)
    query.add_argument("--query-ir", type=Path, required=True)
    query.add_argument("--audit", type=Path, required=True)
    evaluate = subparsers.add_parser("eval", help="run the deterministic P1 Gold Case suite")
    evaluate.add_argument("--metrics", type=Path, required=True)
    evaluate.add_argument("--data", type=Path, required=True)
    evaluate.add_argument("--gold-cases", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, required=True)

    station_flow = subparsers.add_parser(
        "db-station-flow", help="query allowlisted station-flow rows from MySQL"
    )
    station_flow.add_argument("--date", required=True)
    station_flow.add_argument("--station-id", action="append", default=[])
    station_flow.add_argument("--line-id", action="append", default=[])
    station_flow.add_argument("--limit", type=int, default=5_000)
    station_flow.add_argument("--output", type=Path, required=True)
    station_flow.add_argument("--audit", type=Path, required=True)
    station_flow.add_argument("--prompt-password", action="store_true")

    od_flow = subparsers.add_parser(
        "db-od-flow", help="query an allowlisted half-open OD-flow time window"
    )
    od_flow.add_argument("--start", required=True)
    od_flow.add_argument("--end", required=True)
    od_flow.add_argument("--origin-station-id", action="append", type=int, default=[])
    od_flow.add_argument("--destination-station-id", action="append", type=int, default=[])
    od_flow.add_argument("--limit", type=int, default=50_000)
    od_flow.add_argument("--output", type=Path, required=True)
    od_flow.add_argument("--audit", type=Path, required=True)
    od_flow.add_argument("--prompt-password", action="store_true")

    tables = subparsers.add_parser("db-tables", help="list MySQL table metadata")
    tables.add_argument("--limit", type=int, default=200)
    tables.add_argument("--output", type=Path, required=True)
    tables.add_argument("--audit", type=Path, required=True)
    tables.add_argument("--prompt-password", action="store_true")

    describe = subparsers.add_parser("db-describe", help="describe one MySQL table")
    describe.add_argument("--table", required=True)
    describe.add_argument("--output", type=Path, required=True)
    describe.add_argument("--audit", type=Path, required=True)
    describe.add_argument("--prompt-password", action="store_true")

    forecast = subparsers.add_parser(
        "forecast-designated-day",
        help="copy a reference day's station flows onto a designated target day",
    )
    forecast.add_argument("--reference-date", required=True)
    forecast.add_argument("--target-date", required=True)
    forecast.add_argument("--scheme-id", type=int, required=True)
    forecast.add_argument("--limit", type=int, default=50_000)
    forecast.add_argument("--output", type=Path, required=True)
    forecast.add_argument("--audit", type=Path, required=True)
    forecast.add_argument("--prompt-password", action="store_true")
    return parser


def _database_settings(prompt_password: bool) -> DatabaseSettings:
    environment = os.environ.copy()
    if prompt_password and not environment.get("METRO_DB_PASSWORD"):
        environment["METRO_DB_PASSWORD"] = getpass.getpass("Database password: ")
    return DatabaseSettings.from_env(environment)


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        pd.DataFrame(rows).to_csv(path, index=False)
        return
    if path.suffix.lower() == ".json":
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return
    raise ValueError("output file must use .csv or .json")


def _validate_artifact_targets(output: Path, audit: Path) -> None:
    if output.absolute() == audit.absolute():
        raise ValueError("output and audit paths must be different")
    if output.suffix.lower() not in {".csv", ".json"}:
        raise ValueError("output file must use .csv or .json")
    if audit.suffix.lower() != ".json":
        raise ValueError("audit file must use .json")
    existing = [str(path) for path in (output, audit) if path.exists()]
    if existing:
        raise ValueError(f"artifact already exists; refusing overwrite: {', '.join(existing)}")


def _temporary_sibling(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=target.suffix, dir=target.parent, delete=False
    ) as handle:
        return Path(handle.name)


def _publish_database_artifacts(
    output: Path,
    audit: Path,
    rows: list[dict],
    result: DatabaseQueryResult,
    operation: str,
) -> None:
    _validate_artifact_targets(output, audit)
    temporary_output = _temporary_sibling(output)
    temporary_audit: Path | None = None
    output_published = False
    audit_published = False
    try:
        temporary_audit = _temporary_sibling(audit)
        _write_rows(temporary_output, rows)
        write_database_audit(temporary_audit, result, operation=operation)
        # Hard-link publication is atomic and fails if a target appears after the
        # preflight check, so a concurrent writer is never overwritten.
        os.link(temporary_output, output)
        output_published = True
        os.link(temporary_audit, audit)
        audit_published = True
    finally:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            pass
        if temporary_audit is not None:
            try:
                temporary_audit.unlink(missing_ok=True)
            except OSError:
                pass
        if output_published and not audit_published:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass


def _safe_error_payload(exc: Exception, *, database_operation: bool = False) -> dict[str, str]:
    if isinstance(exc, pymysql.MySQLError) or (database_operation and isinstance(exc, OSError)):
        return {
            "status": "error",
            "code": "database_error",
            "error": "database operation failed; inspect authorized local diagnostics",
        }
    return {"status": "error", "code": "invalid_request", "error": str(exc)}


def _print_artifact_summary(
    operation: str,
    row_count: int,
    output: Path,
    audit: Path,
    *,
    truncated: bool,
) -> None:
    print(
        json.dumps(
            {
                "status": "ok",
                "operation": operation,
                "row_count": row_count,
                "truncated": truncated,
                "output": str(output),
                "audit": str(audit),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            summary = validate_repository_contracts(args.metrics, args.gold_cases, args.data)
            print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "query":
            result = execute_query(
                args.metrics,
                args.data,
                load_query_ir(args.query_ir),
                audit_path=args.audit,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "eval":
            report = evaluate_gold_cases(args.metrics, args.data, args.gold_cases)
            write_json_report(args.report, report)
            print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
            return 0 if report["summary"]["failed"] == 0 else 1
        if args.command.startswith("db-"):
            _validate_artifact_targets(args.output, args.audit)
            database = ReadOnlyMetroDatabase(_database_settings(args.prompt_password))
            if args.command == "db-station-flow":
                result = database.query_station_flow_day(
                    date.fromisoformat(args.date),
                    station_ids=args.station_id,
                    line_ids=args.line_id,
                    limit=args.limit,
                )
            elif args.command == "db-od-flow":
                result = database.query_od_flow_window(
                    datetime.fromisoformat(args.start),
                    datetime.fromisoformat(args.end),
                    origin_station_ids=args.origin_station_id,
                    destination_station_ids=args.destination_station_id,
                    limit=args.limit,
                )
            elif args.command == "db-tables":
                result = database.list_tables(limit=args.limit)
                _publish_database_artifacts(
                    args.output, args.audit, result.rows, result, args.command
                )
                _print_artifact_summary(
                    args.command,
                    result.row_count,
                    args.output,
                    args.audit,
                    truncated=result.truncated,
                )
                return 0
            else:
                result = database.describe_table(args.table)
                _publish_database_artifacts(
                    args.output, args.audit, result.rows, result, args.command
                )
                _print_artifact_summary(
                    args.command,
                    result.row_count,
                    args.output,
                    args.audit,
                    truncated=result.truncated,
                )
                return 0
            _publish_database_artifacts(args.output, args.audit, result.rows, result, args.command)
            _print_artifact_summary(
                args.command,
                result.row_count,
                args.output,
                args.audit,
                truncated=result.truncated,
            )
            return 0
        if args.command == "forecast-designated-day":
            _validate_artifact_targets(args.output, args.audit)
            database = ReadOnlyMetroDatabase(_database_settings(args.prompt_password))
            reference_value = args.reference_date.split("&", maxsplit=1)[0]
            result = database.query_station_flow_day(
                date.fromisoformat(reference_value),
                limit=args.limit,
            )
            if not result.rows:
                raise ValueError(f"no station-flow rows found for reference date {reference_value}")
            if result.truncated:
                raise ValueError(
                    "station-flow row limit reached; refusing a possibly truncated forecast"
                )
            forecast = transform_designated_day_flow(
                pd.DataFrame(result.rows),
                target_date=args.target_date,
                scheme_id=args.scheme_id,
            )
            _publish_database_artifacts(
                args.output,
                args.audit,
                forecast.to_dict(orient="records"),
                result,
                args.command,
            )
            _print_artifact_summary(
                args.command, len(forecast), args.output, args.audit, truncated=False
            )
            return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, pymysql.MySQLError) as exc:
        database_operation = (
            args.command.startswith("db-") or args.command == "forecast-designated-day"
        )
        print(
            json.dumps(
                _safe_error_payload(exc, database_operation=database_operation),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
