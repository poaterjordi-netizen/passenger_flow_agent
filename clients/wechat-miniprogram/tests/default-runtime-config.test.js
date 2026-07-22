"use strict"

const assert = require("node:assert/strict")
const path = require("node:path")

global.wx = {
  getStorageSync() {
    return {
      transport: "cloudbase",
      apiBaseUrl: "",
      accessToken: "legacy-should-not-survive"
    }
  },
  setStorageSync() {},
  removeStorageSync() {}
}

const config = require(path.join(__dirname, "..", "miniprogram", "config", "index.js"))
const runtime = config.getRuntimeConfig()

assert.equal(runtime.transport, "http")
assert.equal(runtime.apiBaseUrl, "https://metro.9m-zx.com/assistant-bridge")
assert.equal(runtime.accessToken, "")
process.stdout.write("default runtime migrates legacy CloudBase to fixed Aliyun ingress\n")
