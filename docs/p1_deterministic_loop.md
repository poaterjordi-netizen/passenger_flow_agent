# P1 deterministic query loop

## Scope

P1 accepts an already structured and validated `QueryIR`; it does not interpret free-form language. The loop is:

```text
QueryIR JSON
  -> contract validation and allowlists
  -> fixed metric expression + parameterized SQL template
  -> validated CSV loaded into an in-memory SQLite database
  -> bounded deterministic aggregate query
  -> exact result or Gold Case comparison
  -> JSON result and audit artifact
```

## Safety properties

- Metric expressions, dimension columns, filter fields, and operators come from fixed allowlists.
- User values are bound as SQLite parameters and never concatenated into SQL.
- Time ranges are half-open `[start, end)` and converted to epoch seconds.
- `in` filters contain 1–100 non-empty strings; result limits are 1–1000.
- The synthetic database is created in memory for each execution and exposes no write command.
- The SQL template never embeds filter values. P1 audit files retain the original synthetic QueryIR for reproducibility; a future production adapter must apply field-level redaction before persistence.
- Gold Cases carrying blocked tags such as `privacy` or `scope_escalation` are rejected before execution.

The blocked tags are trusted Gold Case policy metadata for evaluation. P1 does not claim to infer these tags from free-form questions; that classification boundary belongs to P2.

## Verification semantics

For one-dimensional results, a Gold Case mapping such as `{station_id: value}` is compared exactly. Scalar aggregates compare directly. Multi-dimensional cases compare the complete ordered row list. A case passes only when both status and expected value match.

## Explicit non-goals

No LLM, free-form Text-to-SQL, production database, internal schema, user trajectory, credential, deployment, notification, or automated operational action is part of P1.
