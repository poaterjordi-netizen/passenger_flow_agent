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

## P0/P1 components

- `contracts.py`: validates metric registry, Gold Cases, and synthetic data.
- `query_engine.py`: compiles allowlisted QueryIR to parameterized SQL, loads the synthetic SQLite store, executes deterministic aggregates, verifies Gold Cases, and writes audit artifacts.
- `cli.py`: exposes `validate`, `query`, and `eval` commands.
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
- P2: bounded natural-language-to-QueryIR layer and adversarial evaluation.
- P3: explicitly authorized read-only, sanitized real-data pilot.
- P4: private collaboration, CI hardening, and internal integration.
