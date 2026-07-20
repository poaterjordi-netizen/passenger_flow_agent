# Metro Passenger Flow Agent

[![CI](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/ci.yml)
[![Quality](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/quality.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/quality.yml)
[![CodeQL](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/codeql.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/codeql.yml)
[![Documentation Status](https://readthedocs.org/projects/passenger-flow-agent/badge/?version=latest)](https://passenger-flow-agent.readthedocs.io/en/latest/)

Governed passenger-flow query agent for metro operations. The repository separates deterministic contracts and verification from any future language-model layer.

## P1 status

P0 established the product boundary and executable contracts. P1 adds the deterministic query loop:

- validated `QueryIR` compiled to fixed, parameterized SQL templates;
- an in-memory synthetic SQLite store built from the validated CSV fixture;
- deterministic aggregation for entries, exits, transfers, and net inflow;
- exact Gold Case verification and pre-execution rejection of blocked risk tags;
- mandatory per-query audit artifacts with a parameterized SQL template and traceable synthetic QueryIR;
- local CLI, tests, security checks, and CI smoke coverage.

P1 does **not** parse free-form language, connect production systems, execute arbitrary SQL, send notifications, deploy services, or claim production accuracy. Natural-language-to-`QueryIR` belongs to P2.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
metro-agent validate \
  --metrics examples/synthetic_data/metrics.json \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --data examples/synthetic_data/passenger_flow.csv
metro-agent query \
  --metrics examples/synthetic_data/metrics.json \
  --data examples/synthetic_data/passenger_flow.csv \
  --query-ir examples/query_ir/entries_by_station.json \
  --audit /tmp/metro-query-audit.json
metro-agent eval \
  --metrics examples/synthetic_data/metrics.json \
  --data examples/synthetic_data/passenger_flow.csv \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --report /tmp/metro-p1-eval.json
python3 -m unittest discover -s tests -v
```

No third-party runtime dependencies are required for P0 or P1.

## Engineering services

- [Read the Docs](https://passenger-flow-agent.readthedocs.io/en/latest/) publishes the
  versioned project documentation.
- [GitHub Actions](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions)
  runs contract tests, Python 3.11-3.13 compatibility, linting, coverage, package builds,
  documentation checks, and CodeQL analysis.
- [GitHub Security](https://github.com/poaterjordi-netizen/passenger_flow_agent/security)
  provides CodeQL, Dependabot alerts and updates, secret scanning, and push protection.
- Local pre-commit hooks run YAML/JSON hygiene, private-key detection, and Ruff checks.

## Workspaces

- Product source: this Git repository.
- Private Hermes/SAM cockpit: `/Users/xiaobosun/.hermes/saved/research/tasks/20260720_metro_passenger_flow_agent/`.

The cockpit may reference source commits and verification artifacts. It must not be copied into this repository.
