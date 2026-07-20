# Architecture

## Goal

Answer passenger-flow questions with traceable numbers while keeping language interpretation, deterministic computation, verification, audit, and human authorization separate.

## Controlled path

```text
question
  -> intent/semantic parser (future, bounded)
  -> QueryIR schema validation
  -> metric and dimension allowlists
  -> deterministic query planner/compiler
  -> read-only synthetic or authorized analytical store
  -> result verifier
  -> evidence-backed response + audit record
```

## Components

- `contracts.py`: validates metric registry, Gold Cases, and synthetic data.
- `query_engine.py`: compiles allowlisted QueryIR to parameterized SQL, loads the synthetic SQLite store, executes deterministic aggregates, verifies Gold Cases, and writes audit artifacts.
- `database.py`: injects runtime-only MySQL settings, compiles fixed station/OD queries, requires TLS and read-only transactions, enforces limits, and writes redacted audits.
- `forecasting.py`: contains the reusable, database-write-free designated-day station-flow transformation ported from the active legacy path.
- `cli.py`: exposes synthetic validation/evaluation, bounded database queries, metadata inspection, and designated-day forecast commands.
- `schemas/`: machine-readable contracts for QueryIR and Gold Cases.
- `examples/synthetic_data/`: non-sensitive baseline fixtures.
- `tests/`: contract and repository-boundary checks.

## Invariants

1. A model never directly executes SQL.
2. Numbers come from an execution artifact, not language-model recall.
3. Unknown metrics, dimensions, operators, or fields fail closed.
4. Query scope, row count, runtime, and export volume are bounded.
5. Production and external side effects remain human-gated.
6. Hermes reliability evaluation is separate from product acceptance.

## Phases

- P0: contracts and synthetic fixtures — complete.
- P1: deterministic QueryIR-to-result loop on synthetic data — complete.
- P1.5: bounded MySQL adapter and designated-day baseline forecast — implemented; real-data use remains explicitly authorized and local-artifact only.
- P2: bounded natural-language-to-QueryIR layer and adversarial evaluation.
- P3: dedicated least-privilege database identity, verified server CA, sanitized real-data Gold Cases, and cost/timeout evaluation.
- P4: private collaboration, CI hardening, and internal integration.
