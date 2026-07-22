"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

const application = { globalData: { assistantSessionId: "", catalog: null, catalogLoadedAt: 0 } }
let page

global.getApp = () => application
global.Page = (definition) => {
  page = definition
  page.data = JSON.parse(JSON.stringify(definition.data))
  page.setData = (changes) => Object.assign(page.data, changes)
}
global.wx = {
  cloud: {
    callFunction() {
      return Promise.resolve({
        result: {
          statusCode: 502,
          data: { error: { message: "智能分析后端暂时不可用" } }
        }
      })
    }
  },
  getStorageSync() {
    return { configVersion: 2, transport: "cloudbase", apiBaseUrl: "", accessToken: "" }
  },
  showToast() {},
  stopPullDownRefresh() {},
  switchTab() {}
}

require(path.join(__dirname, "..", "miniprogram", "pages", "assistant", "assistant.js"))

async function main() {
  page.refreshRuntime()
  assert.equal(await page.initialize(true), false)
  assert.equal(page.data.sessionId, "")
  assert.match(page.data.error, /云函数可用，但真实智能分析后端不可达/)

  page.submit()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(page.data.sending, false)
  assert.match(page.data.error, /云函数可用，但真实智能分析后端不可达/)
  assert.doesNotMatch(page.data.error, /^智能分析会话未建立$/)
  process.stdout.write("assistant session failure is actionable\n")
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
