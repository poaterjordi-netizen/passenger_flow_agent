# Metric dictionary

The machine registry now carries semantic metadata in addition to deterministic source fields:
version, label, definition, logical dataset, data role, allowed grains, missing-value policy,
quality gate, access policy, and admission status. The synthetic engine still executes every
registered metric, while production-shadow admits only an explicit subset after source approval.

Canonical machine-readable definitions live in `examples/synthetic_data/metrics.json`.

| Metric | Meaning | Aggregation | Unit | Allowed dimensions |
|---|---|---|---|---|
| `entries` | Passengers entering fare gates in interval | sum | passengers | line, station, direction, time |
| `exits` | Passengers exiting fare gates in interval | sum | passengers | line, station, direction, time |
| `transfers` | Recorded interchange events in interval | sum | passengers | line, station, time |
| `net_inflow` | entries minus exits | derived sum | passengers | line, station, direction, time |

## Semantic rules

- Time zone: `Asia/Shanghai`.
- Interval: half-open `[start, end)`.
- Counts are non-negative integers before derived metrics.
- `net_inflow = sum(entries) - sum(exits)` over the same filtered rows.
- Missing rows mean “no observation,” not automatically zero.
- P0 fixtures are synthetic and do not represent actual stations or traffic.
