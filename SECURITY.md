# Security policy

## Repository boundary

Only synthetic fixtures and non-secret adapter code are permitted in Git. Production credentials, connection endpoints, schema inventories, query results, forecasts, ticket/card identifiers, passenger trajectories, logs, and meeting source material must not enter this repository.

## Query safety baseline

P1 compiles constrained `QueryIR` deterministically, allowlists metrics/dimensions/operators, parameterizes values, caps rows and time, and records an audit artifact against an in-memory synthetic store. The MySQL adapter adds fixed dataset routes, verified TLS by default, a read-only transaction, limit-plus-one truncation detection, rollback-only cleanup, timeouts, and paired redacted audits. DDL, DML, multi-statement SQL, comments, unbounded export, and model-generated free-form SQL remain prohibited.

The client-side read-only transaction is defense in depth, not a substitute for least privilege. Production use requires a dedicated database identity with only the necessary `SELECT` and metadata permissions and a CA bundle through `METRO_DB_SSL_CA` for certificate verification. `METRO_DB_ALLOW_INSECURE_TLS=true` is an explicit non-production escape hatch and must not be used for production credentials.

## Human gates

Production access, credential or permission changes, external notifications, deployment, public release, and Git push require explicit authorization and review.

## Reporting

Report suspected leaks privately to the repository owner. Do not open a public issue containing sensitive material.
