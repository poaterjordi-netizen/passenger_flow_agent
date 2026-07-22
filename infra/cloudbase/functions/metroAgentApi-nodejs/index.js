"use strict"

const crypto = require("node:crypto")
const fs = require("node:fs")
const path = require("node:path")

const VERSION = "0.4.3"
const DATA_DIR = process.env.METRO_AGENT_DATA_DIR
  ? path.resolve(process.env.METRO_AGENT_DATA_DIR)
  : __dirname
const METRICS_PATH = path.join(DATA_DIR, "metrics.json")
const DATA_PATH = path.join(DATA_DIR, "passenger_flow.csv")
const ALLOWED_DIMENSIONS = new Set(["line", "station", "direction", "time"])
const DIMENSION_FIELDS = {
  line: "line_id",
  station: "station_id",
  direction: "direction",
  time: "timestamp"
}
const ALLOWED_FILTER_FIELDS = new Set(["line_id", "station_id", "direction"])
const ALLOWED_DIRECTIONS = new Set(["up", "down", "na"])
const METRIC_LABELS = {
  entries: "进站量",
  exits: "出站量",
  transfers: "换乘量",
  net_inflow: "净流入"
}
const DIMENSION_LABELS = {
  line: "线路",
  station: "车站",
  direction: "方向",
  time: "时间"
}
const audits = new Map()
const ASSISTANT_PROXY_LIMIT = 4 * 1024 * 1024

class RouteNotFound extends Error {}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function hasExactKeys(value, expected) {
  if (!isObject(value)) return false
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return actual.length === wanted.length && actual.every((item, index) => item === wanted[index])
}

function assistantBackend() {
  const raw = String(process.env.METRO_ASSISTANT_API_BASE_URL || "").trim().replace(/\/+$/, "")
  if (!raw) return null
  try {
    const value = new URL(raw)
    const localHttp = process.env.METRO_ASSISTANT_ALLOW_HTTP === "true" &&
      value.protocol === "http:" && ["127.0.0.1", "localhost"].includes(value.hostname)
    if (value.protocol !== "https:" && !localHttp) return null
    if ((value.pathname && value.pathname !== "/") || value.search || value.hash) return null
    return value.origin
  } catch (error) {
    return null
  }
}

function assistantHeaders() {
  const headers = { accept: "application/json", "content-type": "application/json" }
  const token = String(process.env.METRO_ASSISTANT_API_ACCESS_TOKEN || "").trim()
  if (token) headers.authorization = `Bearer ${token}`
  return headers
}

async function fetchWithNetworkRetry(url, options, attempts) {
  let lastError
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fetch(url, options)
    } catch (error) {
      lastError = error
      if ((error && error.name === "AbortError") || attempt + 1 >= attempts) throw error
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)))
    }
  }
  throw lastError
}

async function assistantProxyHealth() {
  const backend = assistantBackend()
  if (!backend) {
    return {
      configured: false,
      reachable: false,
      status: "unconfigured",
      transport: "server_side_allowlisted_proxy"
    }
  }
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 5000)
  const startedAt = Date.now()
  try {
    const upstream = await fetchWithNetworkRetry(`${backend}/health`, {
      method: "GET",
      headers: assistantHeaders(),
      signal: controller.signal
    }, 3)
    if (!upstream.ok) {
      return {
        configured: true,
        reachable: false,
        status: `upstream_http_${upstream.status}`,
        transport: "server_side_allowlisted_proxy"
      }
    }
    const data = await upstream.json().catch(() => ({}))
    return {
      configured: true,
      reachable: true,
      status: "ready",
      transport: "server_side_allowlisted_proxy",
      latency_ms: Date.now() - startedAt,
      upstream_version: typeof data.version === "string" ? data.version : null,
      upstream_environment: typeof data.environment === "string" ? data.environment : null,
      upstream_data_scope: typeof data.data_scope === "string" ? data.data_scope : null
    }
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      status: error && error.name === "AbortError" ? "timeout" : "unreachable",
      transport: "server_side_allowlisted_proxy"
    }
  } finally {
    clearTimeout(timeoutId)
  }
}

function assistantRoute(method, requestPath, payload) {
  const routes = [
    ["GET", /^\/api\/v1\/assistant\/capabilities$/],
    ["POST", /^\/api\/v1\/assistant\/sessions$/],
    ["POST", /^\/api\/v1\/assistant\/sessions\/session-[0-9a-f]{32}\/messages$/],
    ["GET", /^\/api\/v1\/assistant\/runs\/run-[0-9a-f]{32}$/],
    ["GET", /^\/api\/v1\/assistant\/runs\/run-[0-9a-f]{32}\/events$/],
    ["POST", /^\/api\/v1\/assistant\/runs\/run-[0-9a-f]{32}\/feedback$/]
  ]
  if (!routes.some(([allowedMethod, pattern]) => method === allowedMethod && pattern.test(requestPath))) {
    return false
  }
  if (method === "GET" && !hasExactKeys(payload, [])) {
    throw new Error("assistant proxy: GET body must be empty")
  }
  if (requestPath.endsWith("/sessions") && !hasExactKeys(payload, [])) {
    throw new Error("assistant proxy: session body must be empty")
  }
  if (requestPath.endsWith("/messages")) {
    if (!hasExactKeys(payload, ["message"]) || typeof payload.message !== "string") {
      throw new Error("assistant proxy: message body is invalid")
    }
    const message = payload.message.trim()
    if (!message || message.length > 4000) throw new Error("assistant proxy: message length is invalid")
  }
  if (requestPath.endsWith("/feedback")) {
    const keys = Object.keys(payload).sort()
    const accepted = ["accepted", "correction"]
    const adopted = ["accepted", "adopted_response", "correction"]
    if (
      !isObject(payload) ||
      (!hasSameMembers(keys, accepted) && !hasSameMembers(keys, adopted)) ||
      typeof payload.accepted !== "boolean" ||
      typeof payload.correction !== "string" ||
      !payload.correction.trim() ||
      payload.correction.length > 4000
    ) {
      throw new Error("assistant proxy: feedback body is invalid")
    }
  }
  return true
}

async function proxyAssistant(method, requestPath, payload) {
  const backend = assistantBackend()
  if (!backend) {
    return response(503, {
      error: {
        code: "assistant_backend_unconfigured",
        message: "智能分析后端代理尚未配置"
      }
    })
  }
  const controller = new AbortController()
  const configuredTimeout = Number(process.env.METRO_ASSISTANT_PROXY_TIMEOUT_MS || 120000)
  const timeoutMs = Math.min(
    180000,
    Math.max(1000, Number.isFinite(configuredTimeout) ? configuredTimeout : 120000)
  )
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  const headers = assistantHeaders()
  try {
    // Quick Tunnels have no availability SLA. fetch only retries transport
    // failures that happen before an HTTP response; AbortError still stops at
    // the function deadline. Reusing the same request protects phone testing
    // from transient CloudBase -> tunnel connection failures.
    const upstream = await fetchWithNetworkRetry(`${backend}${requestPath}`, {
      method,
      headers,
      body: method === "POST" ? JSON.stringify(payload) : undefined,
      signal: controller.signal
    }, 3)
    const declaredLength = Number(upstream.headers.get("content-length") || 0)
    if (declaredLength > ASSISTANT_PROXY_LIMIT) {
      return response(502, { error: { code: "assistant_response_too_large", message: "智能分析响应超过代理上限" } })
    }
    const body = await upstream.text()
    if (Buffer.byteLength(body, "utf8") > ASSISTANT_PROXY_LIMIT) {
      return response(502, { error: { code: "assistant_response_too_large", message: "智能分析响应超过代理上限" } })
    }
    let data
    try {
      data = body ? JSON.parse(body) : {}
    } catch (error) {
      return response(502, { error: { code: "assistant_invalid_response", message: "智能分析后端返回了无效响应" } })
    }
    return response(upstream.status, data)
  } catch (error) {
    const timedOut = error && error.name === "AbortError"
    return response(timedOut ? 504 : 502, {
      error: {
        code: timedOut ? "assistant_backend_timeout" : "assistant_backend_unavailable",
        message: timedOut ? "智能分析后端响应超时" : "智能分析后端暂时不可用"
      }
    })
  } finally {
    clearTimeout(timeoutId)
  }
}

function parseCsv(content) {
  const lines = content.trim().split(/\r?\n/)
  if (lines.length < 2) throw new Error("data: at least one row is required")
  const headers = lines[0].split(",")
  const required = [
    "timestamp",
    "line_id",
    "station_id",
    "direction",
    "entries",
    "exits",
    "transfers"
  ]
  if (!hasSameMembers(headers, required)) throw new Error("data: invalid fields")
  const rows = lines.slice(1).map((line) => {
    const values = line.split(",")
    if (values.length !== headers.length) throw new Error("data: invalid row")
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index]]))
    if (!isTimestamp(row.timestamp)) throw new Error("data: timestamp must include timezone")
    if (!ALLOWED_DIRECTIONS.has(row.direction)) throw new Error("data: invalid direction")
    for (const field of ["entries", "exits", "transfers"]) {
      const value = Number(row[field])
      if (!Number.isInteger(value) || value < 0) throw new Error(`data: invalid ${field}`)
      row[field] = value
    }
    return row
  })
  return rows
}

function hasSameMembers(left, right) {
  if (left.length !== right.length) return false
  const values = new Set(left)
  return values.size === right.length && right.every((item) => values.has(item))
}

function loadRegistry() {
  const payload = JSON.parse(fs.readFileSync(METRICS_PATH, "utf8"))
  if (!isObject(payload) || payload.schema_version !== "1.0" || !Array.isArray(payload.metrics)) {
    throw new Error("metric registry: invalid document")
  }
  const registry = new Map()
  for (const metric of payload.metrics) {
    if (!isObject(metric) || typeof metric.id !== "string" || registry.has(metric.id)) {
      throw new Error("metric registry: invalid metric")
    }
    if (!Array.isArray(metric.dimensions) || metric.dimensions.some((item) => !ALLOWED_DIMENSIONS.has(item))) {
      throw new Error(`metric registry: invalid dimensions for ${metric.id}`)
    }
    if (!Array.isArray(metric.source_fields) || metric.source_fields.length === 0) {
      throw new Error(`metric registry: missing source fields for ${metric.id}`)
    }
    registry.set(metric.id, metric)
  }
  if (registry.size === 0) throw new Error("metric registry: metrics must not be empty")
  return registry
}

function loadRows() {
  return parseCsv(fs.readFileSync(DATA_PATH, "utf8"))
}

function isTimestamp(value) {
  return typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))
}

function isDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function assertQuery(payload, registry) {
  const required = ["metric", "time_range", "dimensions", "filters", "limit"]
  if (!hasExactKeys(payload, required)) throw new Error("query: invalid QueryIR fields")
  if (!registry.has(payload.metric)) throw new Error(`query: unknown metric ${payload.metric}`)
  if (!hasExactKeys(payload.time_range, ["start", "end"])) throw new Error("query: invalid time_range")
  const { start, end } = payload.time_range
  if (!isTimestamp(start) || !isTimestamp(end)) throw new Error("query: timestamps must include timezone")
  if (Date.parse(start) >= Date.parse(end)) throw new Error("query: start must be before end")
  if (!Array.isArray(payload.dimensions) || new Set(payload.dimensions).size !== payload.dimensions.length) {
    throw new Error("query: dimensions must be a unique list")
  }
  const metricDimensions = new Set(registry.get(payload.metric).dimensions)
  if (payload.dimensions.some((item) => !metricDimensions.has(item))) {
    throw new Error(`query: dimension not allowed for metric ${payload.metric}`)
  }
  if (!Array.isArray(payload.filters)) throw new Error("query: filters must be a list")
  for (const filter of payload.filters) {
    if (!hasExactKeys(filter, ["field", "operator", "value"])) throw new Error("query: invalid filter shape")
    if (!ALLOWED_FILTER_FIELDS.has(filter.field) || !["eq", "in"].includes(filter.operator)) {
      throw new Error("query: filter is not allowlisted")
    }
    const values = filter.operator === "eq" ? [filter.value] : filter.value
    if (filter.operator === "eq" && (typeof filter.value !== "string" || !filter.value)) {
      throw new Error("query: eq filter value must be a non-empty string")
    }
    if (filter.operator === "in" && (
      !Array.isArray(values) || values.length < 1 || values.length > 100 ||
      values.some((item) => typeof item !== "string" || !item)
    )) {
      throw new Error("query: in filter value must contain 1 to 100 non-empty strings")
    }
    if (filter.field === "direction" && values.some((item) => !ALLOWED_DIRECTIONS.has(item))) {
      throw new Error("query: invalid direction filter value")
    }
  }
  if (!Number.isInteger(payload.limit) || payload.limit < 1 || payload.limit > 1000) {
    throw new Error("query: limit must be an integer from 1 to 1000")
  }
}

function assertForecast(payload) {
  if (!hasExactKeys(payload, ["reference_date", "target_date", "scheme_id", "limit"])) {
    throw new Error("forecast: invalid request fields")
  }
  if (!isDate(payload.reference_date) || !isDate(payload.target_date)) {
    throw new Error("forecast: dates must use YYYY-MM-DD")
  }
  if (!Number.isInteger(payload.scheme_id) || payload.scheme_id < 0) {
    throw new Error("forecast: scheme_id must be a non-negative integer")
  }
  if (!Number.isInteger(payload.limit) || payload.limit < 1 || payload.limit > 1000) {
    throw new Error("forecast: limit must be an integer from 1 to 1000")
  }
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`
  if (isObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`
  }
  return JSON.stringify(value)
}

function fingerprint(payload) {
  return crypto.createHash("sha256").update(canonicalJson(payload), "utf8").digest("hex")
}

function makeAudit(operation, payload) {
  const record = {
    audit_id: `${operation}-${crypto.randomUUID().replaceAll("-", "")}`,
    created_at: new Date().toISOString(),
    status: "succeeded",
    operation,
    ...payload
  }
  audits.set(record.audit_id, record)
  return summarizeAudit(record)
}

function summarizeAudit(record) {
  return {
    audit_id: record.audit_id,
    created_at: record.created_at,
    status: record.status,
    operation: record.operation,
    row_count: record.row_count,
    query_fingerprint: record.query_fingerprint,
    data_source: record.data_source
  }
}

function metricValue(metric, rows) {
  if (metric === "entries" || metric === "exits" || metric === "transfers") {
    return rows.reduce((total, row) => total + row[metric], 0)
  }
  if (metric === "net_inflow") {
    return rows.reduce((total, row) => total + row.entries - row.exits, 0)
  }
  throw new Error("query: unsupported deterministic aggregation")
}

function executeQuery(payload, registry, sourceRows) {
  assertQuery(payload, registry)
  const start = Date.parse(payload.time_range.start)
  const end = Date.parse(payload.time_range.end)
  const filtered = sourceRows.filter((row) => {
    const timestamp = Date.parse(row.timestamp)
    if (timestamp < start || timestamp >= end) return false
    return payload.filters.every((filter) => {
      const values = filter.operator === "eq" ? [filter.value] : filter.value
      return values.includes(row[filter.field])
    })
  })
  const groups = new Map()
  for (const row of filtered) {
    const key = JSON.stringify(payload.dimensions.map((dimension) => row[DIMENSION_FIELDS[dimension]]))
    const group = groups.get(key) || []
    group.push(row)
    groups.set(key, group)
  }
  if (payload.dimensions.length === 0 && !groups.has("[]")) groups.set("[]", [])
  const rows = [...groups.entries()].map(([key, group]) => {
    const values = JSON.parse(key)
    const result = {}
    payload.dimensions.forEach((dimension, index) => {
      result[dimension] = values[index]
    })
    result[payload.metric] = metricValue(payload.metric, group)
    return result
  })
  rows.sort((left, right) => {
    for (const dimension of payload.dimensions) {
      const comparison = String(left[dimension]).localeCompare(String(right[dimension]), "en")
      if (comparison !== 0) return comparison
    }
    return 0
  })
  const limited = rows.slice(0, payload.limit)
  const audit = makeAudit("query", {
    query_fingerprint: fingerprint(payload),
    query_ir: payload,
    metric: payload.metric,
    dimensions: payload.dimensions,
    row_count: limited.length,
    data_source: "passenger_flow.csv",
    data_scope: "synthetic"
  })
  return {
    status: "answer",
    metric: payload.metric,
    dimensions: payload.dimensions,
    rows: limited,
    row_count: limited.length,
    audit
  }
}

function executeForecast(payload, sourceRows) {
  assertForecast(payload)
  const source = sourceRows.filter((row) => row.timestamp.slice(0, 10) === payload.reference_date)
  if (source.length === 0) throw new Error(`no synthetic rows for reference date ${payload.reference_date}`)
  if (source.length > payload.limit) throw new Error("forecast row limit reached; narrow the requested scope")
  const rows = source.map((row) => ({
    timestamp: `${payload.target_date}${row.timestamp.slice(10)}`,
    line_id: row.line_id,
    station_id: row.station_id,
    direction: row.direction,
    entries: row.entries,
    exits: row.exits,
    transfers: row.transfers,
    scheme_id: payload.scheme_id
  }))
  const audit = makeAudit("forecast", {
    query_fingerprint: fingerprint(payload),
    reference_date: payload.reference_date,
    target_date: payload.target_date,
    scheme_id: payload.scheme_id,
    method: "reference_day_copy",
    row_count: rows.length,
    data_source: "passenger_flow.csv",
    data_scope: "synthetic"
  })
  return {
    status: "answer",
    method: "reference_day_copy",
    reference_date: payload.reference_date,
    target_date: payload.target_date,
    scheme_id: payload.scheme_id,
    rows,
    row_count: rows.length,
    audit
  }
}

function formatOffsetDate(timestamp) {
  const date = new Date(timestamp)
  const shifted = new Date(date.getTime() + 8 * 60 * 60 * 1000)
  return shifted.toISOString().replace(".000Z", "+08:00")
}

function catalog(registry, sourceRows) {
  const ordered = [...sourceRows].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
  const unique = [...new Set(ordered.map((row) => Date.parse(row.timestamp)))].sort((a, b) => a - b)
  let interval = 60 * 60 * 1000
  if (unique.length > 1) {
    interval = Math.min(...unique.slice(1).map((value, index) => value - unique[index]))
  }
  const metrics = [...registry.entries()].map(([id, definition]) => ({
    id,
    label: METRIC_LABELS[id] || id,
    unit: definition.unit || "passengers",
    dimensions: definition.dimensions
  }))
  return {
    data_scope: "synthetic",
    timezone: "Asia/Shanghai",
    metrics,
    dimensions: Object.entries(DIMENSION_LABELS).map(([id, label]) => ({ id, label })),
    lines: [...new Set(sourceRows.map((row) => row.line_id))].sort(),
    stations: [...new Set(sourceRows.map((row) => row.station_id))].sort(),
    directions: [
      { id: "up", label: "上行" },
      { id: "down", label: "下行" },
      { id: "na", label: "不区分" }
    ],
    default_time_range: {
      start: ordered[0].timestamp,
      end: formatOffsetDate(unique[unique.length - 1] + interval)
    },
    available_dates: [...new Set(ordered.map((row) => row.timestamp.slice(0, 10)))].sort()
  }
}

async function route(event) {
  const requestPath = event.path
  const method = String(event.method || "GET").toUpperCase()
  const payload = event.data === undefined || event.data === null ? {} : event.data
  if (typeof requestPath !== "string" || !isObject(payload)) {
    throw new Error("request path and data must be structured values")
  }
  if (requestPath.startsWith("/api/v1/assistant/")) {
    if (!assistantRoute(method, requestPath, payload)) throw new RouteNotFound("route not found")
    return proxyAssistant(method, requestPath, payload)
  }
  const registry = loadRegistry()
  const sourceRows = loadRows()
  if (method === "GET" && requestPath === "/health") {
    return {
      status: "ok",
      service: "metro-passenger-flow-api",
      version: VERSION,
      environment: "cloudbase-wechat",
      data_scope: "synthetic",
      assistant_proxy: await assistantProxyHealth()
    }
  }
  if (method === "GET" && requestPath === "/api/v1/catalog") return catalog(registry, sourceRows)
  if (method === "POST" && requestPath === "/api/v1/queries") return executeQuery(payload, registry, sourceRows)
  if (method === "POST" && requestPath === "/api/v1/forecasts/designated-day") return executeForecast(payload, sourceRows)
  if (method === "GET" && requestPath.startsWith("/api/v1/audits/")) {
    const auditId = requestPath.slice("/api/v1/audits/".length)
    if (!/^(?:query|forecast)-[0-9a-f]{32}$/.test(auditId) || !audits.has(auditId)) {
      throw new RouteNotFound("audit not found")
    }
    return summarizeAudit(audits.get(auditId))
  }
  throw new RouteNotFound("route not found")
}

function response(statusCode, data) {
  return { statusCode, data }
}

exports.main = async (event) => {
  if (!isObject(event)) {
    return response(422, { error: { code: "invalid_request", message: "request must be an object" } })
  }
  try {
    const result = await route(event)
    return result && Number.isInteger(result.statusCode) ? result : response(200, result)
  } catch (error) {
    if (error instanceof RouteNotFound) return response(404, { detail: error.message })
    if (error instanceof Error) {
      return response(422, { error: { code: "invalid_request", message: error.message } })
    }
    return response(500, { error: { code: "internal_error", message: "服务暂时不可用" } })
  }
}
