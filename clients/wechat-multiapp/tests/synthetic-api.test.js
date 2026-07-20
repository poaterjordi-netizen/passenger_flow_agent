const assert = require("node:assert/strict")
const test = require("node:test")

const {
  catalog,
  executeForecast,
  executeQuery,
  sha256,
  syntheticRequest
} = require("../miniprogram/utils/synthetic-api")

const TIME_RANGE = {
  start: "2026-07-20T08:00:00+08:00",
  end: "2026-07-20T10:00:00+08:00"
}

test("uses the standard SHA-256 fingerprint", () => {
  assert.equal(
    sha256("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
  )
})

test("exposes the deterministic synthetic catalog", () => {
  const value = catalog()
  assert.equal(value.data_scope, "synthetic")
  assert.deepEqual(value.lines, ["L-A"])
  assert.deepEqual(value.stations, ["S-ALPHA", "S-BETA"])
  assert.deepEqual(value.default_time_range, TIME_RANGE)
})

test("executes allowlisted QueryIR deterministically", () => {
  const value = executeQuery({
    metric: "entries",
    time_range: TIME_RANGE,
    dimensions: ["station"],
    filters: [],
    limit: 100
  })
  assert.deepEqual(value.rows, [
    { station: "S-ALPHA", entries: 375 },
    { station: "S-BETA", entries: 125 }
  ])
  assert.match(value.audit.audit_id, /^query-[0-9a-f]{32}$/)
  assert.match(value.audit.query_fingerprint, /^[0-9a-f]{64}$/)
})

test("rejects fields outside constrained QueryIR", () => {
  assert.throws(() => executeQuery({
    metric: "entries",
    time_range: TIME_RANGE,
    dimensions: [],
    filters: [],
    limit: 10,
    sql: "SELECT * FROM passenger_flow"
  }), /invalid QueryIR fields/)
})

test("builds the designated-day baseline without writes", () => {
  const value = executeForecast({
    reference_date: "2026-07-20",
    target_date: "2026-07-21",
    scheme_id: 0,
    limit: 100
  })
  assert.equal(value.row_count, 6)
  assert.equal(value.rows[0].timestamp, "2026-07-21T08:00:00+08:00")
  assert.match(value.audit.audit_id, /^forecast-[0-9a-f]{32}$/)
})

test("serves health and cached audit routes asynchronously", async () => {
  const health = await syntheticRequest({ path: "/health" })
  assert.deepEqual(health, {
    status: "ok",
    service: "metro-passenger-flow-api",
    version: "0.1.0",
    environment: "multiapp-offline",
    data_scope: "synthetic"
  })
  const query = await syntheticRequest({
    path: "/api/v1/queries",
    method: "POST",
    data: {
      metric: "entries",
      time_range: TIME_RANGE,
      dimensions: [],
      filters: [],
      limit: 10
    }
  })
  const audit = await syntheticRequest({ path: `/api/v1/audits/${query.audit.audit_id}` })
  assert.equal(audit.audit_id, query.audit.audit_id)
})
