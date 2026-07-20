# Metro Passenger Flow Agent

This project provides a governed passenger-flow query agent for metro operations. It keeps
language-model interpretation separate from deterministic validation and execution.

## Engineering guarantees

- All natural-language requests must compile to constrained `QueryIR` before execution.
- Metrics are registered in `examples/synthetic_data/metrics.json`.
- Contract and Gold Case validation is deterministic and machine-checkable.
- P0 and P1 use synthetic data only; no production database or credential is required.
- Query execution uses fixed templates and parameter binding, never free-form model SQL.

## Documentation map

- [Product boundary](sanitized_requirements.md)
- [Architecture](architecture.md)
- [Deterministic query loop](p1_deterministic_loop.md)
- [Data contract](data_contract.md)
- [Metric dictionary](metric_dictionary.md)
- [Threat model](threat_model.md)

## Local verification

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
metro-agent validate \
  --metrics examples/synthetic_data/metrics.json \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --data examples/synthetic_data/passenger_flow.csv
```

The source repository is available on
[GitHub](https://github.com/poaterjordi-netizen/passenger_flow_agent).
