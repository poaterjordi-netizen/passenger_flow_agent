# Threat model

| Threat | Failure mode | P0/P1 control |
|---|---|---|
| Prompt/SQL injection | arbitrary statement execution | no free-form SQL path; structured IR only |
| Metric hallucination | plausible but undefined number | registry allowlist and fail-closed validation |
| Scope escalation | query outside authorized rows/columns | future row/column policies and read-only identity |
| Sensitive-data commit | internal data enters Git history | synthetic-only policy, ignores, boundary tests, review |
| Cost denial | expensive scan/export | deterministic bounds on time, rows, timeout, explain/cost gate |
| Audit gap | answer cannot be reproduced | question/IR/result/verifier/audit artifacts |
| Model overreach | model makes final authorization choice | deterministic governance and human gates |

Residual P0 risk: repository-level checks cannot prove that future manually added files are sanitized. Every staged diff still requires review and secret scanning before push.
