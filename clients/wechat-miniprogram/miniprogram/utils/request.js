const { getRuntimeConfig } = require("../config/index")

function responseMessage(response) {
  const body = response && response.data
  if (body && body.error && body.error.message) return body.error.message
  if (body && typeof body.detail === "string") return body.detail
  if (body && Array.isArray(body.detail) && body.detail.length) {
    return body.detail.map((item) => item.msg || "参数错误").join("；")
  }
  return `服务返回异常（${response.statusCode || "未知"}）`
}

function networkFailureMessage(url, error) {
  const original = String((error && error.errMsg) || "网络连接失败，请检查 API 地址")
  if (!/url not in domain list/i.test(original)) return original

  let appId = "未知"
  try {
    const account = wx.getAccountInfoSync && wx.getAccountInfoSync()
    appId = (account && account.miniProgram && account.miniProgram.appId) || appId
  } catch (_) {
    // 诊断信息不得影响原始网络错误的处理。
  }
  const match = String(url || "").match(/^https?:\/\/[^/]+/i)
  const requestDomain = match ? match[0] : String(url || "未知")
  return `微信 request 合法域名未对当前小程序生效（AppID：${appId}；请求域名：${requestDomain}）。请确认该域名添加在“开发设置 → 服务器域名 → request 合法域名”，保存后彻底关闭并重新进入小程序。`
}

function cloudRequest(options, config) {
  if (!wx.cloud) return Promise.reject(new Error("当前微信版本不支持云开发"))
  const timeoutMs = Number(options.timeout || 15000)
  const invocation = wx.cloud.callFunction({
    name: config.cloudFunctionName,
    config: { env: config.cloudEnvId },
    data: {
      path: options.path,
      method: options.method || "GET",
      data: options.data || {}
    }
  })
  let timeoutId
  const timeout = new Promise((resolve, reject) => {
    timeoutId = setTimeout(() => reject(new Error("云端响应超时，请稍后重试")), timeoutMs)
  })
  return Promise.race([invocation, timeout]).then((response) => {
    const result = response && response.result
    if (result && result.statusCode >= 200 && result.statusCode < 300) return result.data
    throw new Error(responseMessage({
      data: result && result.data,
      statusCode: result && result.statusCode
    }))
  }).catch((error) => {
    if (error && error.message && !/^cloud\.callFunction/.test(error.message)) throw error
    throw new Error((error && (error.errMsg || error.message)) || "云函数调用失败")
  }).finally(() => {
    if (timeoutId) clearTimeout(timeoutId)
  })
}

function httpRequest(options, config) {
  if (!config.apiBaseUrl) return Promise.reject(new Error("请先配置 API 地址"))
  const headers = { "content-type": "application/json" }
  if (config.accessToken) headers.Authorization = `Bearer ${config.accessToken}`
  const url = `${config.apiBaseUrl}${options.path}`

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method: options.method || "GET",
      data: options.data,
      header: headers,
      timeout: Number(options.timeout || 15000),
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data)
          return
        }
        reject(new Error(responseMessage(response)))
      },
      fail(error) {
        reject(new Error(networkFailureMessage(url, error)))
      }
    })
  })
}

function request(options) {
  const config = getRuntimeConfig()
  return config.transport === "cloudbase"
    ? cloudRequest(options, config)
    : httpRequest(options, config)
}

module.exports = { networkFailureMessage, request }
