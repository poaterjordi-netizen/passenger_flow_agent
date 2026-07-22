"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

const application = {
  globalData: {
    catalog: {
      data_scope: "production-shadow",
      available_dates: ["2023-09-27"]
    }
  }
}
let page
let requestCount = 0

global.getApp = () => application
global.Page = (definition) => {
  page = definition
  page.data = JSON.parse(JSON.stringify(definition.data))
  page.setData = (changes) => Object.assign(page.data, changes)
}
global.wx = {
  getStorageSync() { return {} },
  request() { requestCount += 1 }
}

require(path.join(__dirname, "..", "miniprogram", "pages", "forecast", "forecast.js"))

async function main() {
  page.onLoad()
  await Promise.resolve()
  page.submitForecast()

  assert.equal(page.data.dataScope, "production-shadow")
  assert.match(page.data.error, /真实数据库环境尚未准入指定日复制预测/)
  assert.equal(requestCount, 0)
  process.stdout.write("forecast page does not mislabel a shadow baseline as a real forecast\n")
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
