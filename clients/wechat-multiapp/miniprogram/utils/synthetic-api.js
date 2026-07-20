const { METRICS, ROWS } = require("../data/synthetic")

const VERSION = "0.1.0"
const ALLOWED_DIMENSIONS = ["line", "station", "direction", "time"]
const ALLOWED_FILTER_FIELDS = ["line_id", "station_id", "direction"]
const ALLOWED_DIRECTIONS = ["up", "down", "na"]
const DIMENSION_FIELDS = {
  line: "line_id",
  station: "station_id",
  direction: "direction",
  time: "timestamp"
}
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
const SHA256_CONSTANTS = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]
const audits = {}
let auditSequence = 0

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function hasExactKeys(value, expected) {
  if (!isObject(value)) return false
  const actual = Object.keys(value).sort()
  const wanted = expected.slice().sort()
  return actual.length === wanted.length && actual.every((item, index) => item === wanted[index])
}

function includes(list, value) {
  return list.indexOf(value) !== -1
}

function isTimestamp(value) {
  return typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))
}

function isDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`
  if (isObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`
  }
  return JSON.stringify(value)
}

function rotateRight(value, amount) {
  return (value >>> amount) | (value << (32 - amount))
}

function utf8Bytes(value) {
  const encoded = encodeURIComponent(value)
  const bytes = []
  for (let index = 0; index < encoded.length; index += 1) {
    if (encoded[index] === "%") {
      bytes.push(parseInt(encoded.slice(index + 1, index + 3), 16))
      index += 2
    } else {
      bytes.push(encoded.charCodeAt(index))
    }
  }
  return bytes
}

function hex32(value) {
  let result = (value >>> 0).toString(16)
  while (result.length < 8) result = `0${result}`
  return result
}

function sha256(value) {
  const bytes = utf8Bytes(value)
  const bitLength = bytes.length * 8
  bytes.push(0x80)
  while (bytes.length % 64 !== 56) bytes.push(0)
  const high = Math.floor(bitLength / 0x100000000)
  const low = bitLength >>> 0
  for (let shift = 24; shift >= 0; shift -= 8) bytes.push((high >>> shift) & 0xff)
  for (let shift = 24; shift >= 0; shift -= 8) bytes.push((low >>> shift) & 0xff)

  const hash = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ]
  const words = new Array(64)
  for (let offset = 0; offset < bytes.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      const position = offset + index * 4
      words[index] = (
        (bytes[position] << 24) |
        (bytes[position + 1] << 16) |
        (bytes[position + 2] << 8) |
        bytes[position + 3]
      )
    }
    for (let index = 16; index < 64; index += 1) {
      const left = words[index - 15]
      const right = words[index - 2]
      const sigma0 = rotateRight(left, 7) ^ rotateRight(left, 18) ^ (left >>> 3)
      const sigma1 = rotateRight(right, 17) ^ rotateRight(right, 19) ^ (right >>> 10)
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) | 0
    }

    let a = hash[0]
    let b = hash[1]
    let c = hash[2]
    let d = hash[3]
    let e = hash[4]
    let f = hash[5]
    let g = hash[6]
    let h = hash[7]
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25)
      const choose = (e & f) ^ ((~e) & g)
      const temp1 = (h + sum1 + choose + SHA256_CONSTANTS[index] + words[index]) | 0
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22)
      const majority = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (sum0 + majority) | 0
      h = g
      g = f
      f = e
      e = (d + temp1) | 0
      d = c
      c = b
      b = a
      a = (temp1 + temp2) | 0
    }
    hash[0] = (hash[0] + a) | 0
    hash[1] = (hash[1] + b) | 0
    hash[2] = (hash[2] + c) | 0
    hash[3] = (hash[3] + d) | 0
    hash[4] = (hash[4] + e) | 0
    hash[5] = (hash[5] + f) | 0
    hash[6] = (hash[6] + g) | 0
    hash[7] = (hash[7] + h) | 0
  }
  return hash.map(hex32).join("")
}

function assertQuery(payload) {
  if (!hasExactKeys(payload, ["metric", "time_range", "dimensions", "filters", "limit"])) {
    throw new Error("query: invalid QueryIR fields")
  }
  const metric = METRICS.find((item) => item.id === payload.metric)
  if (!metric) throw new Error(`query: unknown metric ${payload.metric}`)
  if (!hasExactKeys(payload.time_range, ["start", "end"])) throw new Error("query: invalid time_range")
  const { start, end } = payload.time_range
  if (!isTimestamp(start) || !isTimestamp(end)) throw new Error("query: timestamps must include timezone")
  if (Date.parse(start) >= Date.parse(end)) throw new Error("query: start must be before end")
  if (!Array.isArray(payload.dimensions) || new Set(payload.dimensions).size !== payload.dimensions.length) {
    throw new Error("query: dimensions must be a unique list")
  }
  if (payload.dimensions.some((item) => !includes(metric.dimensions, item))) {
    throw new Error(`query: dimension not allowed for metric ${payload.metric}`)
  }
  if (!Array.isArray(payload.filters)) throw new Error("query: filters must be a list")
  payload.filters.forEach((filter) => {
    if (!hasExactKeys(filter, ["field", "operator", "value"])) throw new Error("query: invalid filter shape")
    if (!includes(ALLOWED_FILTER_FIELDS, filter.field) || !includes(["eq", "in"], filter.operator)) {
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
    if (filter.field === "direction" && values.some((item) => !includes(ALLOWED_DIRECTIONS, item))) {
      throw new Error("query: invalid direction filter value")
    }
  })
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

function metricValue(metric, rows) {
  if (includes(["entries", "exits", "transfers"], metric)) {
    return rows.reduce((total, row) => total + row[metric], 0)
  }
  if (metric === "net_inflow") {
    return rows.reduce((total, row) => total + row.entries - row.exits, 0)
  }
  throw new Error("query: unsupported deterministic aggregation")
}

function makeAudit(operation, payload) {
  auditSequence += 1
  const seed = `${Date.now()}:${auditSequence}:${payload.query_fingerprint}`
  const record = {
    audit_id: `${operation}-${sha256(seed).slice(0, 32)}`,
    created_at: new Date().toISOString(),
    status: "succeeded",
    operation,
    ...payload
  }
  audits[record.audit_id] = record
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

function executeQuery(payload) {
  assertQuery(payload)
  const start = Date.parse(payload.time_range.start)
  const end = Date.parse(payload.time_range.end)
  const filtered = ROWS.filter((row) => {
    const timestamp = Date.parse(row.timestamp)
    if (timestamp < start || timestamp >= end) return false
    return payload.filters.every((filter) => {
      const values = filter.operator === "eq" ? [filter.value] : filter.value
      return includes(values, row[filter.field])
    })
  })
  const groups = {}
  filtered.forEach((row) => {
    const key = JSON.stringify(payload.dimensions.map((dimension) => row[DIMENSION_FIELDS[dimension]]))
    if (!groups[key]) groups[key] = []
    groups[key].push(row)
  })
  if (payload.dimensions.length === 0 && !groups["[]"]) groups["[]"] = []
  const rows = Object.keys(groups).map((key) => {
    const values = JSON.parse(key)
    const result = {}
    payload.dimensions.forEach((dimension, index) => { result[dimension] = values[index] })
    result[payload.metric] = metricValue(payload.metric, groups[key])
    return result
  })
  rows.sort((left, right) => {
    for (let index = 0; index < payload.dimensions.length; index += 1) {
      const dimension = payload.dimensions[index]
      const leftValue = String(left[dimension])
      const rightValue = String(right[dimension])
      if (leftValue < rightValue) return -1
      if (leftValue > rightValue) return 1
    }
    return 0
  })
  const limited = rows.slice(0, payload.limit)
  const audit = makeAudit("query", {
    query_fingerprint: sha256(canonicalJson(payload)),
    metric: payload.metric,
    dimensions: payload.dimensions,
    row_count: limited.length,
    data_source: "embedded:passenger_flow.csv",
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

function executeForecast(payload) {
  assertForecast(payload)
  const source = ROWS.filter((row) => row.timestamp.slice(0, 10) === payload.reference_date)
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
    query_fingerprint: sha256(canonicalJson(payload)),
    reference_date: payload.reference_date,
    target_date: payload.target_date,
    scheme_id: payload.scheme_id,
    method: "reference_day_copy",
    row_count: rows.length,
    data_source: "embedded:passenger_flow.csv",
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
  const shifted = new Date(timestamp + 8 * 60 * 60 * 1000)
  return shifted.toISOString().replace(".000Z", "+08:00")
}

function uniqueSorted(values) {
  return Array.from(new Set(values)).sort()
}

function catalog() {
  const ordered = ROWS.slice().sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
  const timestamps = uniqueSorted(ordered.map((row) => Date.parse(row.timestamp))).map(Number).sort((a, b) => a - b)
  let interval = 60 * 60 * 1000
  if (timestamps.length > 1) {
    interval = Math.min.apply(null, timestamps.slice(1).map((value, index) => value - timestamps[index]))
  }
  return {
    data_scope: "synthetic",
    timezone: "Asia/Shanghai",
    metrics: METRICS.map((metric) => ({
      id: metric.id,
      label: METRIC_LABELS[metric.id] || metric.id,
      unit: metric.unit,
      dimensions: metric.dimensions
    })),
    dimensions: ALLOWED_DIMENSIONS.map((id) => ({ id, label: DIMENSION_LABELS[id] })),
    lines: uniqueSorted(ROWS.map((row) => row.line_id)),
    stations: uniqueSorted(ROWS.map((row) => row.station_id)),
    directions: [
      { id: "up", label: "上行" },
      { id: "down", label: "下行" },
      { id: "na", label: "不区分" }
    ],
    default_time_range: {
      start: ordered[0].timestamp,
      end: formatOffsetDate(timestamps[timestamps.length - 1] + interval)
    },
    available_dates: uniqueSorted(ordered.map((row) => row.timestamp.slice(0, 10)))
  }
}

function route(options) {
  const path = options.path
  const method = String(options.method || "GET").toUpperCase()
  const payload = options.data === undefined || options.data === null ? {} : options.data
  if (typeof path !== "string" || !isObject(payload)) throw new Error("request path and data must be structured values")
  if (method === "GET" && path === "/health") {
    return {
      status: "ok",
      service: "metro-passenger-flow-api",
      version: VERSION,
      environment: "multiapp-offline",
      data_scope: "synthetic"
    }
  }
  if (method === "GET" && path === "/api/v1/catalog") return catalog()
  if (method === "POST" && path === "/api/v1/queries") return executeQuery(payload)
  if (method === "POST" && path === "/api/v1/forecasts/designated-day") return executeForecast(payload)
  if (method === "GET" && path.indexOf("/api/v1/audits/") === 0) {
    const auditId = path.slice("/api/v1/audits/".length)
    if (!/^(?:query|forecast)-[0-9a-f]{32}$/.test(auditId) || !audits[auditId]) {
      throw new Error("audit not found")
    }
    return summarizeAudit(audits[auditId])
  }
  throw new Error("route not found")
}

function syntheticRequest(options) {
  return Promise.resolve().then(() => route(options || {}))
}

module.exports = {
  canonicalJson,
  catalog,
  executeForecast,
  executeQuery,
  sha256,
  syntheticRequest
}
