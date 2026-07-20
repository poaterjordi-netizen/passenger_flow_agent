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

function cloudRequest(options, config) {
  if (!wx.cloud) return Promise.reject(new Error("当前微信版本不支持云开发"))
  const invocation = wx.cloud.callFunction({
    name: config.cloudFunctionName,
    config: { env: config.cloudEnvId },
    data: {
      path: options.path,
      method: options.method || "GET",
      data: options.data || {}
    }
  })
  const timeout = new Promise((resolve, reject) => {
    setTimeout(() => reject(new Error("云端响应超时，请稍后重试")), 15000)
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
  })
}

function httpRequest(options, config) {
  if (!config.apiBaseUrl) return Promise.reject(new Error("请先配置 API 地址"))
  const headers = { "content-type": "application/json" }
  if (config.accessToken) headers.Authorization = `Bearer ${config.accessToken}`

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.apiBaseUrl}${options.path}`,
      method: options.method || "GET",
      data: options.data,
      header: headers,
      timeout: 15000,
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data)
          return
        }
        reject(new Error(responseMessage(response)))
      },
      fail(error) {
        reject(new Error(error.errMsg || "网络连接失败，请检查 API 地址"))
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

module.exports = { request }
