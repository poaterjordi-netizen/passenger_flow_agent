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

QueryIR v2 adds optional routing fields while keeping legacy synthetic Gold Cases valid:

- `metric_version`: must match the registered semantic version;
- `city`: mandatory for production-shadow and resolved by the protected intent;
- `dataset_role`: `actual`, `reference`, or `forecast`; station-flow shadow admits `actual` only;
- `source_version`: mandatory for production-shadow and must match the external registry;
- `time_grain`: must be admitted by the metric and source registration;
- `time_basis`: `event_time` or explicitly governed `service_day`;
- `timezone`: currently fixed to `Asia/Shanghai`;
- `service_day` and `calendar_version`: both required when service-day semantics are selected;
- `comparison_periods`: explicit baseline/comparison windows and their relation; comparison tools
  never infer同比/环比 by silently splitting a returned result;
- `cross_midnight_policy`: reject by default, or use an approved service-day calendar;
- `data_as_of`: optional evidence cut-off timestamp;
- `order_by`: at most two registered dimension/metric fields with `asc` or `desc`.

当前 station-flow 执行器只实现 source grain + event-time 语义。因此非 source `time_grain`、`service_day/calendar_version`、`data_as_of`或非 reject 的跨午夜策略即使通过通用 schema，也会在执行前明确拒绝，不会“接受但忽略”。只有实现对应日历/分组/截止语义并加入契约测试后才能扩展允许值。

Synthetic execution remains the deterministic baseline. Production-shadow additionally requires
an external, approved, quality-passing source registration. Its physical mapping is a fixed
adapter route, never a model-selected table name.

Global Top-N is executed as a complete governed aggregation/order/limit operation. Derived totals,
growth, correlation, anomalies and trends declare complete-input requirements and fail when an
upstream `ToolResult` is incomplete or truncated.

`EvidencePacket` v2 records result schema, structured claims, returned and matched counts,
completeness/truncation, query fingerprint, logical-plan hash, result hash, upstream evidence IDs,
calculation method, policy snapshot, access-scope hash, warnings and block reason. The first 20 rows
remain a display bound and are never treated as the complete population.
在合成回答前，verifier 会从对应 `ToolResult` 重算 result hash，并精确验证 source refs/upstream lineage、policy snapshot、access scope、complete/truncated 和无环性。需要证据却没有 Evidence、引用不完整 Evidence 或任一绑定不一致均是硬失败。

Unknown or ambiguous semantics fail closed and return a clarification request; they are not guessed.
