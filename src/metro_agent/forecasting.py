from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol

import pandas as pd

_REQUIRED_STATION_FLOW_COLUMNS = (
    "StationID",
    "StationName",
    "LineName",
    "StartTime",
    "EndTime",
    "InFlow",
    "OutFlow",
)


class StationFlowQueryResult(Protocol):
    rows: list[dict]
    truncated: bool


class StationFlowSource(Protocol):
    def query_station_flow_day(
        self, reference_date: date, *, limit: int
    ) -> StationFlowQueryResult: ...


def _parse_date(value: str | date, field_name: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def transform_designated_day_flow(
    reference_flow: pd.DataFrame,
    *,
    target_date: str | date,
    scheme_id: int,
    created_at: datetime | None = None,
) -> pd.DataFrame:
    """Move a reference day's station flows onto a target service date.

    This is the active forecasting rule from the supplied legacy script: station
    inflow/outflow values are copied unchanged while each interval keeps its time
    of day and receives the requested target date and scheme ID. The function is
    pure with respect to the input frame and performs no database writes.
    """

    missing = sorted(set(_REQUIRED_STATION_FLOW_COLUMNS) - set(reference_flow.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    if not isinstance(scheme_id, int) or isinstance(scheme_id, bool) or scheme_id < 0:
        raise ValueError("scheme_id must be a non-negative integer")
    service_date = _parse_date(target_date, "target_date")
    # Match the legacy script's local `time.localtime` semantics while keeping an
    # aware datetime internally when the caller does not inject a test timestamp.
    timestamp = created_at or datetime.now().astimezone()

    output = reference_flow.loc[:, _REQUIRED_STATION_FLOW_COLUMNS].copy(deep=True)
    start_times = pd.to_datetime(output["StartTime"], errors="raise")
    end_times = pd.to_datetime(output["EndTime"], errors="raise")
    if start_times.isna().any() or end_times.isna().any():
        raise ValueError("StartTime and EndTime must contain valid timestamps")
    if start_times.dt.tz is not None or end_times.dt.tz is not None:
        raise ValueError("StartTime and EndTime must use naive local timestamps")

    durations = end_times - start_times
    if (durations == timedelta(0)).any():
        raise ValueError("station-flow intervals must have positive duration")
    rollover = durations < timedelta(0)
    adjusted_end_times = end_times.copy()
    adjusted_end_times.loc[rollover] = adjusted_end_times.loc[rollover] + timedelta(days=1)
    durations = adjusted_end_times - start_times
    if (durations <= timedelta(0)).any() or (durations > timedelta(days=1)).any():
        raise ValueError("station-flow intervals must be positive and at most one day")

    target_starts = pd.to_datetime(
        service_date.isoformat() + " " + start_times.dt.strftime("%H:%M:%S"),
        errors="raise",
    )
    target_ends = target_starts + durations
    output["StartTime"] = target_starts.dt.strftime("%Y-%m-%d %H:%M:%S")
    output["EndTime"] = target_ends.dt.strftime("%Y-%m-%d %H:%M:%S")
    output["CreateTime"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    output["SchemeID"] = scheme_id
    return output


def forecast_designated_day(
    database: StationFlowSource,
    *,
    reference_date: str | date,
    target_date: str | date,
    scheme_id: int,
    created_at: datetime | None = None,
    limit: int = 50_000,
) -> pd.DataFrame:
    """Read one reference day and return a reusable designated-day forecast.

    The old command accepted multiple reference dates separated by ``&`` but only
    consumed the first one. That compatibility is retained explicitly instead of
    being hidden in command-line parsing.
    """

    if isinstance(reference_date, str):
        reference_value = reference_date.split("&", maxsplit=1)[0]
    else:
        reference_value = reference_date
    parsed_reference_date = _parse_date(reference_value, "reference_date")
    result = database.query_station_flow_day(parsed_reference_date, limit=limit)
    if not result.rows:
        raise ValueError(f"no station-flow rows found for reference date {parsed_reference_date}")
    if result.truncated:
        raise ValueError("station-flow row limit reached; refusing a possibly truncated forecast")
    return transform_designated_day_flow(
        pd.DataFrame(result.rows),
        target_date=target_date,
        scheme_id=scheme_id,
        created_at=created_at,
    )
