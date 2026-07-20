# Security policy

## P0 boundary

Only synthetic data is permitted. Production credentials, internal hostnames, database schemas, ticket/card identifiers, passenger trajectories, logs, and meeting source material must not enter this repository.

## Query safety baseline

P1 compiles constrained `QueryIR` deterministically, allowlists metrics/dimensions/operators, parameterizes values, caps rows and time, and records an audit artifact against an in-memory synthetic store. DDL, DML, multi-statement SQL, comments, unbounded export, and model-generated free-form SQL are prohibited. A future production adapter must additionally enforce a read-only database identity, row/column policy, query cost limits, timeouts, and audit redaction.

## Human gates

Production access, credential or permission changes, external notifications, deployment, public release, and Git push require explicit authorization and review.

## Reporting

Report suspected leaks privately to the repository owner. Do not open a public issue containing sensitive material.
