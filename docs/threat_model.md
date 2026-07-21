# Threat model

| Threat | Failure mode | P0/P1 control |
|---|---|---|
| Prompt/SQL injection | arbitrary statement execution | no free-form SQL path; structured IR only |
| Metric hallucination | plausible but undefined number | registry allowlist and fail-closed validation |
| Scope escalation / IDOR | query outside scope or another user's run/audit | server-created AccessContext; city/metric/role/time/row bounds; owner + tenant + scope-hash checks |
| Sensitive-data commit | internal data enters Git history | synthetic-only policy, ignores, boundary tests, review |
| Cost denial | expensive scan/export | deterministic bounds on time, rows, timeout, explain/cost gate |
| Audit gap | answer or model disclosure cannot be reproduced | question/IR/result/verifier artifacts; call-level egress record persisted before invocation; exact payload/endpoint hashes and terminal status |
| Partial-result misstatement | truncated rows reported as global total/rank | complete/truncated contract; matched/returned counts; exact Top-N query; derived-tool complete-input gate |
| Real data leaves boundary | Intent/Evidence sent to an unapproved or substituted model endpoint | separate intent/evidence policies; deny by default; exact provider + model + target-hash binding; minimal envelopes; deterministic fallback |
| Missing data becomes a plausible zero | NULL/string/non-finite/negative flow is silently aggregated | required-field type/domain validation; fail closed; per-query source/missing/invalid counts and runtime quality |
| Forged derived input | MCP caller supplies partial/fabricated rows to rank/growth | derived tools requiring trusted upstream are not MCP-exposed; internal dependency injection uses server ToolResult |
| Evidence substitution | hash, lineage, owner scope, or completeness is forged | recompute result hashes; exact source/scope/policy bindings; acyclic lineage; incomplete Evidence is a hard error |
| Model overreach | model makes final authorization choice | deterministic governance and human gates |

Residual P0 risk: repository-level checks cannot prove that future manually added files are sanitized. Every staged diff still requires review and secret scanning before push.
