"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

const catalog = {
  data_scope: "production-shadow",
  city: "metroflow-city-unverified",
  source_version: "clear-stationflow-day-20230927-live-v1",
  default_time_range: {
    start: "2023-09-27T06:00:00+08:00",
    end: "2023-09-27T07:00:00+08:00"
  },
  metrics: [
    { id: "entries", label: "进站量" },
    { id: "exits", label: "出站量" },
    { id: "net_inflow", label: "净流入" }
  ]
}
const application = { globalData: { catalog: null, catalogLoadedAt: 0 } }
const queryPayloads = []
let page

global.getApp = () => application
global.Page = (definition) => {
  page = definition
  page.data = JSON.parse(JSON.stringify(definition.data))
  page.setData = (changes) => Object.assign(page.data, changes)
}
global.wx = {
  getStorageSync() {
    return {
      configVersion: 2,
      transport: "http",
      apiBaseUrl: "https://metro.9m-zx.com/assistant-bridge",
      accessToken: ""
    }
  },
  request(options) {
    if (options.url.endsWith("/api/v1/catalog")) {
      options.success({ statusCode: 200, data: catalog })
      return
    }
    queryPayloads.push(options.data)
    options.success({
      statusCode: 200,
      data: {
        rows: options.data.dimensions.includes("station")
          ? [{ station: "0101", entries: 7 }]
          : [{ [options.data.metric]: 7 }]
      }
    })
  }
}

require(path.join(__dirname, "..", "miniprogram", "pages", "dashboard", "dashboard.js"))

async function main() {
  await page.loadDashboard()
  assert.equal(queryPayloads.length, 4)
  queryPayloads.forEach((payload) => {
    assert.equal(payload.city, catalog.city)
    assert.equal(payload.source_version, catalog.source_version)
  })
  assert.equal(page.data.scopeLabel, "真实数据库影子环境")
  assert.equal(page.data.error, "")
  process.stdout.write("dashboard production queries preserve admitted source identity\n")
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
