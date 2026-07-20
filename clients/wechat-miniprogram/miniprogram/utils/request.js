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

function request(options) {
  const config = getRuntimeConfig()
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

module.exports = { request }
