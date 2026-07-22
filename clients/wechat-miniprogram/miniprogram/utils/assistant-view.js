"use strict"

const MAX_TABLE_ROWS = 500
const MAX_COLUMNS = 6

function stringValue(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback || "—"
  return String(value)
}

function safeJson(value, limit) {
  let text
  try {
    text = JSON.stringify(value === undefined ? null : value)
  } catch (error) {
    text = "无法序列化"
  }
  const maximum = limit || 1600
  return text.length > maximum ? `${text.slice(0, maximum)}…` : text
}

function compactHash(value) {
  const text = stringValue(value, "")
  return text.length > 16 ? `${text.slice(0, 12)}…` : text || "—"
}

function flattenEvidence(evidence) {
  if (!evidence) return []
  return [
    ...(evidence.facts || []),
    ...(evidence.statistics || []),
    ...(evidence.charts || []),
    ...(evidence.model_outputs || []),
    ...(evidence.knowledge_sources || [])
  ]
}

function externalLinks(tools) {
  const byUrl = new Map()
  ;(tools || []).forEach((tool) => {
    const summary = tool.summary || {}
    ;[summary.navigation_links, summary.source_refs].forEach((items) => {
      if (!Array.isArray(items)) return
      items.forEach((item) => {
        if (!item || typeof item !== "object") return
        if (typeof item.label !== "string" || typeof item.url !== "string") return
        if (!item.url.startsWith("https://")) return
        byUrl.set(item.url, { label: item.label, url: item.url })
      })
    })
  })
  return [...byUrl.values()]
}

function tableView(tools) {
  const rows = []
  ;(tools || []).forEach((tool) => {
    ;(tool.rows || []).forEach((row, index) => {
      if (row && typeof row === "object" && !Array.isArray(row)) {
        rows.push({ key: `${tool.step_id || tool.tool}-${index}`, row })
      }
    })
  })
  const columns = rows.length ? Object.keys(rows[0].row).slice(0, MAX_COLUMNS) : []
  const visible = rows.slice(0, MAX_TABLE_ROWS).map((entry) => ({
    key: entry.key,
    cells: columns.map((column) => ({
      key: `${entry.key}-${column}`,
      value: stringValue(entry.row[column])
    }))
  }))
  return {
    columns: columns.map((column) => ({ key: column, label: column })),
    rows: visible,
    total: rows.length,
    truncated: rows.length > visible.length,
    notice: rows.length > visible.length
      ? `结果共 ${rows.length} 行，小程序当前展示前 ${visible.length} 行。`
      : ""
  }
}

function runtimeLabel(runtime) {
  if (!runtime) return "未报告"
  if (runtime.mode === "local_governed_model") return "Hermes 本地受治理模型"
  if (runtime.mode === "openai_compatible") return "OpenAI-compatible"
  return "离线确定性"
}

function formatCapabilities(capabilities) {
  if (!capabilities) return null
  const runtime = capabilities.active_runtime || {}
  return {
    dataScope: stringValue(capabilities.data_scope),
    provider: stringValue(runtime.provider),
    model: stringValue(runtime.model, "未配置模型"),
    modelActive: runtime.real_model_active === true,
    registryVersion: stringValue(capabilities.capability_registry_version),
    operationCount: (capabilities.operation_capabilities || []).length,
    stages: (capabilities.architecture || []).map((stage, index) => ({
      key: stage.id || String(index),
      index: String(index + 1).padStart(2, "0"),
      label: stringValue(stage.label),
      owner: stage.owner === "llm" ? "大模型" : stage.owner === "human" ? "人工" : "确定性",
      detail: stringValue(stage.detail)
    })),
    productionGaps: capabilities.production_gaps || []
  }
}

function formatRun(run) {
  const frame = run.semantic_frame || null
  const operation = run.operation_ir || {}
  const capability = run.capability_match || {}
  const response = run.response || {}
  const verification = run.verification || null
  const runtime = run.model_runtime || {}
  const tools = run.tool_results || []
  const egress = run.model_egress || []
  const memory = run.semantic_memory_snapshot || {}
  const table = tableView(tools)
  const verified = Boolean(verification && verification.valid === true)
  const verificationFailed = Boolean(verification && verification.valid === false)
  const evidence = flattenEvidence(run.evidence).map((item, index) => ({
    key: item.evidence_id || String(index),
    id: stringValue(item.evidence_id),
    kind: stringValue(item.kind),
    claim: stringValue(item.claim),
    complete: item.complete !== false && item.truncated !== true,
    returned: item.returned_row_count === undefined ? "—" : String(item.returned_row_count),
    matched: item.matched_count_unknown
      ? "unknown"
      : item.matched_row_count === undefined ? "—" : String(item.matched_row_count),
    coverage: item.coverage
      ? `${stringValue(item.coverage.coverage_type)} · ${stringValue(item.coverage.scope_label)}`
      : "unknown",
    queryHash: compactHash(item.query_fingerprint)
  }))

  return {
    raw: run,
    runId: stringValue(run.run_id),
    question: stringValue(run.original_question),
    status: stringValue(run.status),
    completed: run.status === "completed",
    needsClarification: run.status === "needs_clarification",
    taskType: stringValue(run.intent && run.intent.task_type, "understand"),
    provider: stringValue(run.provider),
    intentRoute: stringValue(run.intent_route),
    semanticSource: stringValue(run.semantic_source, "未编译"),
    semanticRoute: stringValue(frame && frame.route),
    operation: stringValue(operation.operation, "未编译"),
    answerPolicy: stringValue(operation.answer_policy, "未选择"),
    capabilityId: stringValue(capability.capability_id, "未匹配"),
    failureCategory: stringValue(run.failure_category, ""),
    semantic: frame ? {
      route: stringValue(frame.route),
      operations: (frame.operations || []).join("、") || "—",
      target: stringValue(frame.target_kind, "unspecified"),
      confidence: `${Math.round(Number(frame.confidence || 0) * 100)}%`,
      goal: stringValue(frame.goal),
      entities: (run.entity_resolutions || []).map((item, index) => ({
        key: `${item.type}-${item.raw_text}-${index}`,
        type: stringValue(item.type),
        reference: stringValue(item.reference, "named"),
        status: stringValue(item.status),
        resolved: item.status === "resolved",
        rawText: stringValue(item.raw_text),
        selected: item.selected_name
          ? `${item.selected_name}（${stringValue(item.selected_id)}）`
          : stringValue(item.selected_id, "未解析")
      })),
      metrics: (run.metric_resolutions || []).map((item, index) => ({
        key: `${item.raw_text}-${index}`,
        status: stringValue(item.status),
        resolved: item.status === "resolved" || item.status === "defaulted",
        rawText: stringValue(item.raw_text),
        selected: stringValue(item.selected_metric, "未解析")
      })),
      memoryEntities: safeJson(memory.current_entities || {}, 800),
      memoryMetric: stringValue(memory.current_metric),
      memoryTime: safeJson(memory.current_time_range || {}, 800),
      disagreements: (run.semantic_disagreements || []).join("；") || "没有结构差异，或本次使用降级语义。"
    } : null,
    runtime: {
      provider: stringValue(runtime.provider || run.provider),
      model: stringValue(runtime.model, "未配置"),
      mode: runtimeLabel(runtime),
      realModel: runtime.real_model_configured === true,
      modelCalls: Number(runtime.model_calls || 0),
      providerCalls: Number(runtime.provider_calls || 0),
      totalTokens: runtime.total_tokens === null || runtime.total_tokens === undefined
        ? "未报告"
        : String(runtime.total_tokens),
      elapsed: runtime.elapsed_seconds === null || runtime.elapsed_seconds === undefined
        ? "未报告"
        : `${runtime.elapsed_seconds}s`,
      status: stringValue(runtime.invocation_status, "not_applicable"),
      egressCount: egress.length,
      approvedEgressCount: egress.filter((item) => item.decision === "approved").length
    },
    verification: {
      verified,
      failed: verificationFailed,
      label: verified ? "确定性核验已通过" : verificationFailed ? "核验失败，禁止采纳" : "等待核验",
      warnings: verification ? verification.warnings || [] : [],
      errors: verification ? verification.errors || [] : [],
      evidenceCount: verification ? (verification.supported_evidence_refs || []).length : 0
    },
    response: {
      answer: stringValue(response.answer, "尚未生成回答"),
      policyNotice: operation.answer_policy === "llm_general"
        ? "GPT 通用知识回答：未把一般知识冒充数据库结果。"
        : operation.answer_policy === "llm_hybrid"
          ? "混合回答：数据库事实与一般知识/推断分开。"
          : "",
      keyFindings: response.key_findings || [],
      recommendations: verified ? response.recommendations || [] : [],
      hiddenRecommendations: !verified && Boolean((response.recommendations || []).length),
      assumptions: response.assumptions || [],
      limitations: response.limitations || [],
      followUps: response.follow_up_questions || []
    },
    plan: (run.plan && run.plan.steps || []).map((step) => ({
      key: step.step_id,
      id: stringValue(step.step_id),
      tool: stringValue(step.tool),
      dependencies: (step.depends_on || []).join("、") || "none",
      arguments: safeJson(step.arguments || {})
    })),
    tools: tools.map((tool, index) => ({
      key: tool.step_id || String(index),
      id: stringValue(tool.step_id),
      tool: stringValue(tool.tool),
      status: stringValue(tool.status),
      success: tool.status === "success",
      complete: tool.complete !== false && tool.truncated !== true,
      claim: stringValue(tool.summary && tool.summary.claim, `${(tool.rows || []).length} rows`),
      returned: tool.returned_row_count === undefined ? "—" : String(tool.returned_row_count),
      matched: tool.matched_count_unknown
        ? "unknown"
        : tool.matched_row_count === undefined ? "—" : String(tool.matched_row_count),
      queryHash: compactHash(tool.query_fingerprint),
      resultHash: compactHash(tool.result_hash),
      blockReason: stringValue(tool.block_reason, "")
    })),
    events: (run.events || []).map((event, index) => ({
      key: `${event.timestamp || "event"}-${index}`,
      state: stringValue(event.state),
      detail: stringValue(event.detail)
    })),
    evidence,
    table,
    externalLinks: externalLinks(tools)
  }
}

module.exports = {
  MAX_TABLE_ROWS,
  compactHash,
  formatCapabilities,
  formatRun,
  safeJson
}
