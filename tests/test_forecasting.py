import unittest
from datetime import date, datetime

import pandas as pd

from metro_agent.forecasting import forecast_designated_day, transform_designated_day_flow


class FakeDatabase:
    def __init__(self, rows, *, truncated=False):
        self.rows = rows
        self.truncated = truncated
        self.calls = []

    def query_station_flow_day(self, reference_date, *, limit):
        self.calls.append((reference_date, limit))
        return self


class DesignatedDayForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_rows = [
            {
                "StationID": "101",
                "StationName": "Alpha",
                "LineName": "Line 1",
                "StartTime": datetime(2023, 9, 27, 6, 0),
                "EndTime": datetime(2023, 9, 27, 6, 30),
                "InFlow": 12,
                "OutFlow": 9,
            },
            {
                "StationID": "102",
                "StationName": "Beta",
                "LineName": "Line 1",
                "StartTime": datetime(2023, 9, 27, 6, 0),
                "EndTime": datetime(2023, 9, 27, 6, 30),
                "InFlow": 8,
                "OutFlow": 7,
            },
        ]

    def test_transform_preserves_flow_and_moves_times_to_target_date(self) -> None:
        source = pd.DataFrame(self.reference_rows)
        created_at = datetime(2026, 7, 20, 12, 0)
        result = transform_designated_day_flow(
            source,
            target_date=date(2024, 9, 29),
            scheme_id=58,
            created_at=created_at,
        )

        self.assertEqual(result["InFlow"].sum(), 20)
        self.assertEqual(result["OutFlow"].sum(), 16)
        self.assertEqual(set(result["SchemeID"]), {58})
        self.assertEqual(set(result["CreateTime"]), {"2026-07-20 12:00:00"})
        self.assertTrue(result["StartTime"].str.startswith("2024-09-29 ").all())
        self.assertEqual(source.iloc[0]["StartTime"], datetime(2023, 9, 27, 6, 0))

    def test_forecast_uses_first_legacy_reference_date(self) -> None:
        database = FakeDatabase(self.reference_rows)
        result = forecast_designated_day(
            database,
            reference_date="2023-09-27&2023-09-20",
            target_date="2024-09-29",
            scheme_id=58,
            created_at=datetime(2026, 7, 20, 12, 0),
        )
        self.assertEqual(database.calls, [(date(2023, 9, 27), 50000)])
        self.assertEqual(len(result), 2)

    def test_missing_columns_fail_with_actionable_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            transform_designated_day_flow(
                pd.DataFrame([{"StationID": "101"}]),
                target_date=date(2024, 9, 29),
                scheme_id=58,
            )

    def test_empty_reference_day_fails_closed(self) -> None:
        database = FakeDatabase([])
        with self.assertRaisesRegex(ValueError, "no station-flow rows"):
            forecast_designated_day(
                database,
                reference_date="2023-09-27",
                target_date="2024-09-29",
                scheme_id=58,
            )

    def test_forecast_refuses_a_possibly_truncated_reference_day(self) -> None:
        database = FakeDatabase(self.reference_rows, truncated=True)
        with self.assertRaisesRegex(ValueError, "row limit reached"):
            forecast_designated_day(
                database,
                reference_date="2023-09-27",
                target_date="2024-09-29",
                scheme_id=58,
            )

    def test_transform_preserves_cross_midnight_interval(self) -> None:
        row = dict(self.reference_rows[0])
        row["StartTime"] = datetime(2023, 9, 27, 23, 50)
        row["EndTime"] = datetime(2023, 9, 27, 0, 10)
        result = transform_designated_day_flow(
            pd.DataFrame([row]), target_date="2024-02-29", scheme_id=58
        )
        self.assertEqual(result.loc[0, "StartTime"], "2024-02-29 23:50:00")
        self.assertEqual(result.loc[0, "EndTime"], "2024-03-01 00:10:00")

    def test_transform_rejects_missing_interval_time(self) -> None:
        row = dict(self.reference_rows[0])
        row["EndTime"] = None
        with self.assertRaisesRegex(ValueError, "valid timestamps"):
            transform_designated_day_flow(
                pd.DataFrame([row]), target_date="2024-09-29", scheme_id=58
            )

    def test_transform_rejects_zero_duration_interval(self) -> None:
        row = dict(self.reference_rows[0])
        row["EndTime"] = row["StartTime"]
        with self.assertRaisesRegex(ValueError, "positive duration"):
            transform_designated_day_flow(
                pd.DataFrame([row]), target_date="2024-09-29", scheme_id=58
            )


if __name__ == "__main__":
    unittest.main()
