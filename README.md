# Metro Passenger Flow Agent

[![CI](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/ci.yml)
[![Quality](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/quality.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/quality.yml)
[![CodeQL](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/codeql.yml/badge.svg)](https://github.com/poaterjordi-netizen/passenger_flow_agent/actions/workflows/codeql.yml)
[![Documentation Status](https://readthedocs.org/projects/passenger-flow-agent/badge/?version=latest)](https://passenger-flow-agent.readthedocs.io/en/latest/)

Governed passenger-flow query agent for metro operations. The repository separates deterministic contracts and verification from any future language-model layer.

## Current status

P0 established the product boundary and executable contracts. P1 adds the deterministic query loop:

- validated `QueryIR` compiled to fixed, parameterized SQL templates;
- an in-memory synthetic SQLite store built from the validated CSV fixture;
- deterministic aggregation for entries, exits, transfers, and net inflow;
- exact Gold Case verification and pre-execution rejection of blocked risk tags;
- mandatory per-query audit artifacts with a parameterized SQL template and traceable synthetic QueryIR;
- local CLI, tests, security checks, and CI smoke coverage.

Version 0.3 adds an explicit, bounded MySQL adapter and ports the active designated-day forecast from the supplied legacy script. The adapter uses runtime-only credentials, verified TLS by default, read-only transactions, fixed parameterized queries, truncation detection, rollback-only cleanup, and paired redacted audit artifacts. It does not expose arbitrary SQL or any database write path.

The designated-day forecast copies the station inflow/outflow pattern from a reference date to a target calendar date and adds the scheme metadata. It returns a local CSV/JSON artifact; it does not insert forecasts or update scheme state.

Version 0.4 adds the governed assistant workflow: natural-language intent, a structured task graph, an allowlisted deterministic tool registry, Evidence Packets, response verification, replayable trajectories, six assistant API capabilities/routes, a Web intelligent-analysis page, and 100 end-to-end Gold Cases. Local and CI execution defaults to an offline `FakeProvider`; isolated Hermes Codex shadow and OpenAI-compatible adapters can use GPT-5.6-sol only when the corresponding runtime environment is explicitly configured.

The current hardening layer adds server-created `AccessContext`, owner-isolated session/run/audit records, explicit QueryIR comparison and service-day semantics, completeness-aware ToolResult/EvidencePacket v2, exact global Top-N execution, deterministic intent/planner routing, model-data-egress policy, two-layer logical/physical source registries, and a blocked-by-default production promotion gate. The API now evaluates that gate at runtime and exposes a redacted `/api/v1/governance/status` contract; the Web client uses it to constrain sessions, queries, forecasts, evidence completeness, and provenance displays. Production-shadow Assistant and report export remain disabled unless separately approved.

Natural-language requests now compile into `OperationIR` and match a versioned capability registry before planning. Entity/metric/date discovery, dataset summaries, endpoint-complete travel planning, and capability help use deterministic tools with explicit `CoverageEvidence` and zero model calls; complex data analysis continues to use GPT only for evidence-grounded synthesis. Meaningful open questions that do not map to a data tool use a one-call `general_answer` fallback with an explicit “no database rows / no live external data” boundary, while truly underspecified requests still clarify. Travel planning separates external places from metro database entities, serves sourced registered routes when available, and otherwise hands off to a live map without inventing a route. The Web UI exposes the selected operation, capability, answer policy, coverage scope, failure category, general-knowledge boundary, and clickable navigation/source links, while a local trace-clustering CLI turns repeated failures into regression candidates.

The project still does **not** execute model-generated SQL, send notifications, schedule background reports, connect real camera/bus/GIS feeds, take automatic operating actions, or claim production prediction accuracy. Cross-network, event, real-time, SOP and geo paths use explicitly synthetic fixtures and remain behind later production and human gates.

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
python3 scripts/evaluate_assistant.py --output /tmp/metro-assistant-eval.json
```

Read-only database and forecast usage is documented in [`docs/database_and_forecast.md`](docs/database_and_forecast.md). Credentials are injected at runtime and never committed.

## WeChat Mini Program first version

The repository now includes a native WeChat Mini Program under
`clients/wechat-miniprogram/` and a synthetic-default FastAPI service under
`src/metro_agent/api/`. The mobile client provides a dashboard, constrained
QueryIR form, result charts and tables, designated-day baseline preview, audit
summary, and runtime connection settings. It never connects directly to MySQL.

Start the local API from the repository root:

```bash
python3 -m pip install -e .
metro-agent-api
```

Open `http://127.0.0.1:8000/docs` for the generated API contract. Import
`clients/wechat-miniprogram/` into WeChat DevTools and use the Settings tab to
select the local or HTTPS staging API. Full setup and phone-testing instructions
are in [`docs/mobile_miniprogram.md`](docs/mobile_miniprogram.md).

## WeChat multi-end application

The isolated project in `clients/wechat-multiapp/` reuses the governed,
synthetic-only Mini Program experience for Android, iOS, and HarmonyOS without
changing the layout of `clients/wechat-miniprogram/`. Its audited application
name is `客流智控`; all three native identifiers are fixed to
`com.sunxb.metroflow`.

An Android debug APK can be built and installed locally. iOS and HarmonyOS
sources and local certificate requests are prepared, while external membership,
certificate issuance, and store signing are intentionally deferred. See
[`clients/wechat-multiapp/README.md`](clients/wechat-multiapp/README.md) for the
verified artifact, security boundaries, and exact resume procedure.

## Web dashboard and local server stack

The React 19 dashboard in `clients/web/` provides the governed passenger-flow
overview, intelligent-analysis workflow with tool and state-machine timelines,
constrained QueryIR workbench, baseline forecast preview, audit lookup, and
system boundary page. Its TypeScript API client is generated from this
FastAPI application's OpenAPI contract.

```bash
cd clients/web
npm ci
npm run dev
```

For the containerized frontend, reverse proxy, backend, and health-check stack,
run `docker compose up --build` on a Docker-enabled host. It binds to
`127.0.0.1:8080` by default. See
[`docs/web_and_deployment.md`](docs/web_and_deployment.md) for regeneration,
testing, deployment boundaries, and the explicit production human gates.
The provider contract, Phase 0–7 implementation matrix and evaluation commands
are documented in [`docs/assistant_architecture.md`](docs/assistant_architecture.md).

For the explicitly acknowledged local shadow path that uses a real read-only MySQL source and
real GPT-5.6 Sol calls, prepare the external Keychain/TLS configuration described in
[`docs/database_and_forecast.md`](docs/database_and_forecast.md), then run:

```bash
METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED=true ./scripts/run_live_local.sh
```

The local site opens at `http://127.0.0.1:5173/real-shadow/`. The public external-test,
operator-supervised Aliyun ingress is documented in
[`docs/real_shadow_demo.md`](docs/real_shadow_demo.md). Both surfaces identify the runtime as a
real-data shadow, not as a production operational system.

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
