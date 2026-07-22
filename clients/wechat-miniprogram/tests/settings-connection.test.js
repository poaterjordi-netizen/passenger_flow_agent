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
    callFunction(options) {
      if (options.data.path !== "/health") throw new Error("unexpected assistant request")
      return Promise.resolve({
        result: {
          statusCode: 200,
          data: {
            status: "ok",
            version: "0.4.1",
            environment: "cloudbase-wechat",
            data_scope: "synthetic",
            assistant_proxy: {
              configured: true,
              reachable: false,
              status: "unreachable"
            }
          }
        }
      })
    }
  },
  getStorageSync() {
    return { configVersion: 2, transport: "cloudbase", apiBaseUrl: "", accessToken: "" }
  },
  setStorageSync() {},
  removeStorageSync() {},
  showToast() {}
}

require(path.join(__dirname, "..", "miniprogram", "pages", "settings", "settings.js"))

async function main() {
  page.onShow()
  page.testConnection()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.ok(page.data.health)
  assert.equal(page.data.assistantReady, false)
  assert.match(page.data.error, /CloudBase 已连接，但真实智能分析后端不可达/)
  assert.equal(application.globalData.assistantSessionId, "")
  process.stdout.write("settings detects unreachable assistant backend\n")
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`)
  process.exit(1)
})
