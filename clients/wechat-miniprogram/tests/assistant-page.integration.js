"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

const apiBaseUrl = String(process.env.METRO_MINIPROGRAM_TEST_API || "http://127.0.0.1:8000")
  .replace(/\/+$/, "")
const application = { globalData: { assistantSessionId: "", catalog: null, catalogLoadedAt: 0 } }
let page

global.getApp = () => application
global.Page = (definition) => {
  page = definition
  page.data = JSON.parse(JSON.stringify(definition.data))
  page.setData = (changes) => Object.assign(page.data, changes)
}
global.wx = {
  getStorageSync() {
    return { configVersion: 2, transport: "http", apiBaseUrl, accessToken: "" }
  },
  request(options) {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), Number(options.timeout || 15000))
    fetch(options.url, {
      method: options.method || "GET",
      headers: options.header,
      body: (options.method || "GET") === "GET" ? undefined : JSON.stringify(options.data || {}),
      signal: controller.signal
    }).then(async (response) => {
      const data = await response.json()
      options.success({ statusCode: response.status, data })
    }).catch((error) => options.fail({ errMsg: error.message })).finally(() => clearTimeout(timeoutId))
  },
  setClipboardData() {},
  showToast() {},
  stopPullDownRefresh() {},
  switchTab() {}
}

require(path.join(__dirname, "..", "miniprogram", "pages", "assistant", "assistant.js"))

async function main() {
  page.refreshRuntime()
  assert.equal(await page.initialize(true), true)
  assert.ok(page.data.sessionId.startsWith("session-"), page.data.error)
  assert.equal(page.data.capabilities.model, "gpt-5.6-sol")
  const establishedSessionId = page.data.sessionId
  page.data.sessionId = ""
  page.data.initializing = false
  page.onShow()
  assert.equal(page.data.sessionId, establishedSessionId)

  const first = await page.sendMessage(
    page.data.sessionId,
    "查一号线各站进站量",
    false
  )
  page.acceptRun(first)
  assert.equal(page.data.result.status, "completed")
  assert.equal(page.data.result.semantic.route, "data")
  assert.match(page.data.result.semantic.memoryEntities, /L010/)
  assert.ok(page.data.result.runtime.modelCalls >= 1)
  assert.ok(page.data.result.table.total >= 1)

  const followUp = await page.sendMessage(
    page.data.sessionId,
    "那就按进站量从高到低排序，并只看前5个站呢？",
    false
  )
  page.acceptRun(followUp)
  assert.equal(page.data.result.status, "completed")
  assert.match(page.data.result.semantic.memoryEntities, /L010/)
  assert.match(page.data.result.response.answer, /前5|前 5|0104/)

  process.stdout.write(JSON.stringify({
    sessionId: page.data.sessionId,
    firstRun: first.run_id,
    followUpRun: followUp.run_id,
    route: page.data.result.semantic.route,
    operation: page.data.result.operation,
    verified: page.data.result.verification.verified,
    modelCalls: page.data.result.runtime.modelCalls,
    tableRows: page.data.result.table.total
  }) + "\n")
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
