# Sanitized P0 requirements

## Users

- Operations analyst: asks for passenger-flow aggregates and comparisons.
- Metric owner: defines metric semantics and validates business meaning.
- Security/data owner: approves data scope and permissions.
- Auditor: traces question, contract, execution, and answer.

## P0 functional requirements

| ID | Requirement | P0 evidence |
|---|---|---|
| REQ-P0-001 | Keep project state and product source in separate workspaces | README, external cockpit |
| REQ-P0-002 | Define machine-readable metric semantics | `metrics.json`, metric dictionary |
| REQ-P0-003 | Define passenger-flow input contract | data contract, synthetic CSV |
| REQ-P0-004 | Define constrained structured query contract | `query_ir.schema.json` |
| REQ-P0-005 | Define reproducible Gold Case format | schema and `gold_cases.json` |
| REQ-P0-006 | Validate contracts without production access | CLI and unit tests |
| REQ-P0-007 | Prevent sensitive material from entering source control | `.gitignore`, SECURITY.md, tests |
| REQ-P0-008 | Run contract checks in CI | GitHub Actions workflow |

## Non-goals

- Production database access or complete internal schema replication.
- Direct free-form Text-to-SQL execution.
- Prediction, causal diagnosis, automated operations, notifications, or deployment.
- Public demo, GitHub Pages, or claims of real-world accuracy/performance.

## P0 acceptance

All JSON and CSV fixtures parse; metric IDs and dimensions agree; all Gold Cases validate; synthetic rows satisfy the data contract; unit tests pass; repository contains no known credential or production-data carrier.
