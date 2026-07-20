# Metro Passenger Flow Agent

Governed passenger-flow query agent for metro operations. The repository separates deterministic contracts and verification from any future language-model layer.

## P0 status

P0 establishes the product boundary and executable contracts:

- sanitized requirements and architecture;
- metric dictionary and passenger-flow data contract;
- constrained `QueryIR` and Gold Case schemas;
- synthetic passenger-flow data and Gold Cases;
- local contract validator, tests, security policy, and CI.

P0 does **not** connect production systems, execute arbitrary SQL, send notifications, deploy services, or claim model accuracy. P1 will implement the deterministic query loop against synthetic data.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
metro-agent validate   --metrics examples/synthetic_data/metrics.json   --gold-cases examples/synthetic_data/gold_cases.json   --data examples/synthetic_data/passenger_flow.csv
python3 -m unittest discover -s tests -v
```

No third-party runtime dependencies are required for P0.

## Workspaces

- Product source: this Git repository.
- Private Hermes/SAM cockpit: `/Users/xiaobosun/.hermes/saved/research/tasks/20260720_metro_passenger_flow_agent/`.

The cockpit may reference source commits and verification artifacts. It must not be copied into this repository.
