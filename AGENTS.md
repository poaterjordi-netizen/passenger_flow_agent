# Repository operating rules

- Product correctness, traceability, and read-only safety come before agent autonomy or presentation.
- P0 is contract-only and uses synthetic data. Do not connect production databases, copy internal schemas, or add credentials.
- Natural language must compile to a constrained QueryIR before deterministic execution; never execute free-form model SQL.
- Every metric must exist in `examples/synthetic_data/metrics.json`; every gold case must be machine-validatable.
- Keep private SAM state in the external project cockpit, not in this repository.
- Before completion run `python3 -m unittest discover -s tests -v` and the contract validation CLI.
- Push, public release, production access, permissions, notifications, and destructive actions require the father's explicit gate.
