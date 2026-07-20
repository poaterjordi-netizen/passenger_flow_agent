# Passenger-flow data contract

## Dataset

P0 uses `examples/synthetic_data/passenger_flow.csv` only.

| Field | Type | Required | Rule |
|---|---|---:|---|
| `timestamp` | ISO-8601 datetime | yes | timezone-aware, interval start |
| `line_id` | string | yes | synthetic stable identifier |
| `station_id` | string | yes | synthetic stable identifier |
| `direction` | enum | yes | `up`, `down`, or `na` |
| `entries` | integer | yes | >= 0 |
| `exits` | integer | yes | >= 0 |
| `transfers` | integer | yes | >= 0 |

Primary observation key: `(timestamp, line_id, station_id, direction)`.

## QueryIR semantics

- `metric`: one registered metric ID.
- `time_range`: timezone-aware `start` and `end`, where start < end.
- `dimensions`: allowlisted subset of the metric's dimensions.
- `filters`: allowlisted fields with explicit operators.
- `limit`: positive and no greater than 1000 in P0/P1.

Unknown or ambiguous semantics fail closed and return a clarification request; they are not guessed.
