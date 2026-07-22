const assert = require("node:assert/strict")
const path = require("node:path")

global.wx = {
  getAccountInfoSync() {
    return { miniProgram: { appId: "wxcec9562590faa1a0" } }
  }
}

const { networkFailureMessage } = require(path.resolve(
  __dirname,
  "../miniprogram/utils/request.js"
))

const message = networkFailureMessage(
  "https://metro.9m-zx.com/assistant-bridge/health",
  { errMsg: "request:fail url not in domain list" }
)

assert.match(message, /wxcec9562590faa1a0/)
assert.match(message, /https:\/\/metro\.9m-zx\.com/)
assert.match(message, /request 合法域名/)
assert.equal(
  networkFailureMessage("https://example.com/health", { errMsg: "request:fail timeout" }),
  "request:fail timeout"
)

console.log("request domain failure includes actionable AppID and domain")
