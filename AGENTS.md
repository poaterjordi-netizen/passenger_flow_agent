# Repository operating rules

- Product correctness, traceability, and read-only safety come before agent autonomy or presentation.
- Synthetic QueryIR remains the deterministic baseline. Real MySQL access is limited to the read-only adapter in `metro_agent.database`; never add credentials, production rows, schema inventories, forecasts, or query artifacts to Git.
- Natural language must compile to a constrained QueryIR before deterministic execution; never execute free-form model SQL.
- Every metric must exist in `examples/synthetic_data/metrics.json`; every gold case must be machine-validatable.
- Keep private SAM state in the external project cockpit, not in this repository.
- Database operations must verify TLS server identity by default, start a read-only transaction, use fixed/parameterized queries, detect truncation, roll back, and atomically publish redacted audits with results.
- Before completion run `python3 -m unittest discover -s tests -v`, Ruff, and the contract validation CLI.
- Push, public release, production access, permissions, notifications, and destructive actions require the father's explicit gate.
