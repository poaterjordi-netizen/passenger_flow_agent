# Security policy

## P0 boundary

Only synthetic data is permitted. Production credentials, internal hostnames, database schemas, ticket/card identifiers, passenger trajectories, logs, and meeting source material must not enter this repository.

## Query safety baseline

Future execution must use a read-only database identity, compile constrained `QueryIR` deterministically, allowlist metrics/dimensions/operators, parameterize values, cap rows and time, and record an audit artifact. DDL, DML, multi-statement SQL, comments, unbounded export, and model-generated free-form SQL are prohibited.

## Human gates

Production access, credential or permission changes, external notifications, deployment, public release, and Git push require explicit authorization and review.

## Reporting

Report suspected leaks privately to the repository owner. Do not open a public issue containing sensitive material.
