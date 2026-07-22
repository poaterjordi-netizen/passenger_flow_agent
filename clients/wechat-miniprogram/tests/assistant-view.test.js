"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

const {
  formatCapabilities,
  formatRun
} = require(path.join(__dirname, "..", "miniprogram", "utils", "assistant-view.js"))

const capabilities = formatCapabilities({
  data_scope: "production-shadow",
  capability_registry_version: "2026-07-21.9",
  active_runtime: {
    provider: "hermes-openai-codex:gpt-5.6-sol",
    model: "gpt-5.6-sol",
    real_model_active: true
  },
  architecture: [{ id: "understand", label: "通用语义编译", owner: "llm", detail: "GPT first" }],
  operation_capabilities: [{ id: "metric_query" }],
  production_gaps: []
})

assert.equal(capabilities.modelActive, true)
assert.equal(capabilities.stages[0].owner, "大模型")
assert.equal(capabilities.operationCount, 1)

const view = formatRun({
  run_id: "run-00000000000000000000000000000000",
  original_question: "查一号线各站进站量",
  status: "completed",
  provider: "hermes-openai-codex:gpt-5.6-sol",
  intent_route: "semantic_model",
  semantic_source: "model",
  semantic_frame: {
    route: "data",
    operations: ["query"],
    target_kind: "station",
    confidence: 0.99,
    goal: "查询一号线各站进站量"
  },
  entity_resolutions: [{
    raw_text: "一号线",
    type: "line",
    reference: "named",
    status: "resolved",
    selected_id: "L010",
    selected_name: "1号线"
  }],
  metric_resolutions: [{
    raw_text: "进站量",
    status: "resolved",
    selected_metric: "entries"
  }],
  semantic_memory_snapshot: {
    current_entities: { line: ["L010"] },
    current_metric: "entries",
    current_time_range: { start: "2023-09-27T06:00:00+08:00", end: "2023-09-27T07:00:00+08:00" }
  },
  intent: { task_type: "query" },
  operation_ir: { operation: "query_metric", answer_policy: "deterministic_summary" },
  capability_match: { capability_id: "metric_query" },
  model_runtime: {
    provider: "hermes-openai-codex:gpt-5.6-sol",
    model: "gpt-5.6-sol",
    mode: "local_governed_model",
    real_model_configured: true,
    model_calls: 1,
    provider_calls: 1,
    total_tokens: 1200,
    elapsed_seconds: 12.3,
    invocation_status: "succeeded"
  },
  model_egress: [{ decision: "approved" }],
  response: {
    answer: "entries 查询返回 1 行，合计 444",
    key_findings: ["0104站 444人次"],
    recommendations: ["核验后处置"],
    limitations: ["production-shadow"],
    assumptions: [],
    follow_up_questions: ["是否继续排序？"]
  },
  verification: {
    valid: true,
    warnings: [],
    errors: [],
    supported_evidence_refs: ["ev-s1"]
  },
  plan: { steps: [{ step_id: "s1", tool: "query_metric", arguments: {}, depends_on: [] }] },
  tool_results: [{
    step_id: "s1",
    tool: "query_metric",
    status: "success",
    rows: [{ station: "0104", entries: 444 }],
    summary: {
      claim: "entries 查询返回 1 行，合计 444",
      navigation_links: [
        { label: "实时地图", url: "https://example.com/map" },
        { label: "禁止链接", url: "http://example.com/plain" }
      ]
    },
    complete: true,
    truncated: false,
    returned_row_count: 1,
    matched_row_count: 1
  }],
  evidence: {
    facts: [{ evidence_id: "ev-s1", kind: "fact", claim: "0104站 444人次", complete: true }],
    statistics: [], charts: [], model_outputs: [], knowledge_sources: []
  },
  events: [{ timestamp: "t1", state: "RESPOND", detail: "完成" }]
})

assert.equal(view.semantic.route, "data")
assert.equal(view.semantic.entities[0].selected, "1号线（L010）")
assert.match(view.semantic.memoryEntities, /L010/)
assert.equal(view.verification.verified, true)
assert.equal(view.table.total, 1)
assert.deepEqual(view.table.columns.map((item) => item.label), ["station", "entries"])
assert.equal(view.evidence.length, 1)
assert.equal(view.externalLinks.length, 1)
assert.equal(view.response.recommendations.length, 1)

const rejected = formatRun({
  run_id: "run-11111111111111111111111111111111",
  original_question: "测试",
  status: "failed",
  response: { answer: "未核验", recommendations: ["不得展示"] },
  verification: { valid: false, warnings: [], errors: ["unsupported"] }
})
assert.equal(rejected.response.recommendations.length, 0)
assert.equal(rejected.response.hiddenRecommendations, true)

process.stdout.write("assistant view formatter ok\n")
