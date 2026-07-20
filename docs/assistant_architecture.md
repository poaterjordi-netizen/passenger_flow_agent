# Governed metro assistant architecture

The assistant is an agentic workflow with a fixed state machine and replaceable model boundary. It does not expose model-generated SQL or an arbitrary function surface.

## Runtime loop

`RECEIVE → UNDERSTAND → CLARIFY → PLAN → EXECUTE_TOOLS → OBSERVE → REPLAN → SYNTHESIZE → VERIFY → RESPOND`

The outer workflow is deterministic. A provider can interpret, plan and compose, while the tool registry computes all query, statistical, forecast, transfer, GIS and report values. The default local mode is `FakeProvider`, which lets development, CI, Gold Case evaluation and demonstrations run without network access or credentials. `OpenAICompatibleProvider` is the production-endpoint adapter. `HermesCodexProvider` is a local shadow-only bridge to an existing Hermes OpenAI Codex OAuth session.

## Provider configuration

Offline/default:

```bash
export METRO_ASSISTANT_PROVIDER=fake
metro-agent-api
```

GPT-5.6-sol through an OpenAI-compatible endpoint:

```bash
export METRO_ASSISTANT_PROVIDER=openai
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export OPENAI_API_KEY='injected-by-secret-manager'
# Optional only when using a compatible gateway:
export OPENAI_BASE_URL='https://gateway.example/v1'
metro-agent-api
```

Local GPT-5.6-sol shadow through an already authenticated Hermes installation:

```bash
export METRO_ASSISTANT_PROVIDER=hermes-codex
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export METRO_ASSISTANT_HERMES_COMMAND=hermes
metro-agent-api
```

The Hermes bridge executes isolated one-shot calls with `--safe-mode` and a minimal ephemeral
toolset. It delegates OAuth resolution to Hermes and never reads or copies Hermes credentials.
It is deliberately not the production deployment route: use the OpenAI-compatible adapter and
an approved secret manager for production. The bridge currently buffers each one-shot response;
it does not provide token-by-token SSE.

Do not commit a key or put provider objects in business code. The adapter contract is:

- `generate_structured(...)`
- `generate_tool_calls(...)`
- `synthesize_from_evidence(...)`
- `stream_text(...)`

## Stable contracts and modules

- `assistant/schemas.py`: `IntentEnvelope`, `EventSpec`, `TransferAnalysisSpec`, `ActionPlan`, `TaskPlan`, `ToolResult`, `EvidencePacket`, `AssistantResponse`, run/session, feedback, dataset-gate and verifier records.
- `assistant/provider.py`: deterministic test provider, OpenAI-compatible endpoint adapter and local Hermes Codex shadow bridge.
- `assistant/context_builder.py`: bounded catalog, dictionary, recent history and tool context.
- `assistant/orchestrator.py`: state machine, clarification stop, dependency scheduling, bounded parallel execution, partial-failure continuation and one novel replan attempt.
- `assistant/tool_registry.py`: allowlisted deterministic tools.
- `assistant/evidence.py`: evidence normalization.
- `assistant/verifier.py`: task-plan, evidence-reference, finite-number and answer-number support hard gates.
- `assistant/trace_store.py`: atomic, replayable session and run trajectories. A trajectory stores selected context, intent, plan, replans, tool calls/results, evidence, response, verifier, human feedback, final adoption and dataset eligibility.

## Tool coverage

The registry includes the first governed implementation of:

- metric catalog, QueryIR query, period comparison and ranking;
- multi-line parallel comparison and synthetic ticket/line/hour multidimensional statistics;
- growth, Pearson and lagged correlation, anomaly detection and trend decomposition;
- reference-day and event-rule forecast baselines and sample evaluation;
- simulated rail/bus transactions, transfer-window matching and threshold comparison;
- simulated station geocoding, OD heatmap and commuting profile;
- simulated capacity thresholds and operating SOP retrieval;
- simulated operating-indicator alignment and human-gated action candidates;
- diagnosis hypothesis evidence and local report artifacts.

All cross-network, GIS, event, real-time and SOP fixtures are explicitly synthetic. Event factors are architecture-validation rules, not validated model accuracy. SOP actions are recommendations requiring human confirmation.

## HTTP and Web

- `POST /api/v1/assistant/sessions`
- `POST /api/v1/assistant/sessions/{session_id}/messages`
- `GET  /api/v1/assistant/runs/{run_id}`
- `GET  /api/v1/assistant/runs/{run_id}/events`
- `POST /api/v1/assistant/runs/{run_id}/feedback`

The Web “智能分析” page keeps the multi-turn conversation and shows the latest verified answer, task type, provider, tool timeline, state-machine events, Evidence Packet cards, result table, deterministic chart, limitations and human-gated recommendations.

## Phase 0–7 completion matrix

| Phase | Working artifact | Verifier |
| --- | --- | --- |
| 0 provider contract | `provider.py`, Fake and OpenAI-compatible providers, structured and streaming methods | `tests/test_assistant.py` |
| 1 natural-language QueryIR loop | metric/line/station/direction/dimension/Top-N extraction, multi-turn scope inheritance, QueryIR → QueryEngine → evidence → answer | argument-level tests and Web multi-turn E2E |
| 2 multi-tool orchestrator | dependency graph, real concurrent independent batch, partial failure, one novel bounded replan | thread-barrier concurrency test, failure/replan trajectory assertions |
| 3 statistics/anomaly/trend | deterministic statistical tools | unit and 100-case evaluation |
| 4 event forecast | reference-day baseline plus explicit rule scenario and SOP | tool test and forecast Gold Cases |
| 5 transfer/GIS | synthetic two-network matching and geo/OD datasets | Gold Cases |
| 6 real-time/report | simulated signals, thresholds, SOP, human-gated action candidates and saved local report | Gold Cases and artifact readback |
| 7 evaluation/demo | exactly 100 distinct end-to-end Gold Cases and Web intelligent-analysis page | semantic Gold checks and Playwright |

## Evaluation

```bash
python scripts/build_assistant_gold_cases.py
python scripts/evaluate_assistant.py --output /tmp/assistant-eval.json
python scripts/evaluate_gpt56_shadow.py \
  --case-id assistant-001 --case-id assistant-021 --case-id assistant-081 \
  --output /tmp/gpt56-shadow.json
python scripts/run_scheduled_assistant.py --output /tmp/daily-report.json
python scripts/export_verified_dataset.py \
  --run-dir /path/to/assistant/traces/runs \
  --output-dir /tmp/verified-dataset
```

`run_scheduled_assistant.py` is a one-shot, verified report runner intended for an external scheduler. It does not install cron, send notifications or create a long-lived background task.

The 100 cases are not numbered copies. They use distinct business questions and verify expected tool sets, parameters, state-machine coverage, successful tool status, evidence kinds, artifact existence, non-causal limitations and human-confirmation boundaries. A passing case is a structurally verified dataset candidate, not proof of production accuracy.

Only a valid structured trajectory with successful tools, supported evidence references and a passing verifier may become a future dataset candidate. A normal runtime trajectory remains ineligible until it either passes the Gold evaluation or receives explicit human feedback and a final adopted response through the feedback API. The project never manufactures a human label.

`export_verified_dataset.py` applies the eligibility, verifier, tool-success, missing-evidence and adoption gates again before writing `intent_understanding.jsonl`, `task_planning.jsonl`, `tool_calling.jsonl` and `evidence_response.jsonl`. Rejected run IDs and reasons are retained only in the export manifest; their contents are not copied into training files.

## Remaining production gates

The complete local architecture is not equivalent to production deployment. The following still require separate data, security, performance and human decisions: real operating data, real event/camera feeds, production SOP approval, authentication/authorization, tested forecast accuracy, scheduled execution, notification delivery, public network exposure, and any automatic operational action.
