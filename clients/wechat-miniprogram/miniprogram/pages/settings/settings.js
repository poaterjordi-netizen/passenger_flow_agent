const {
  clearRuntimeConfig,
  getRuntimeConfig,
  normalizeBaseUrl,
  saveRuntimeConfig
} = require("../../config/index")
const { request } = require("../../utils/request")

Page({
  data: {
    accessToken: "",
    apiBaseUrl: "",
    error: "",
    health: null,
    showToken: false,
    testing: false
  },

  onShow() {
    const config = getRuntimeConfig()
    this.setData({
      accessToken: config.accessToken,
      apiBaseUrl: config.apiBaseUrl,
      error: "",
      health: null
    })
  },

  onBaseUrlInput(event) { this.setData({ apiBaseUrl: event.detail.value }) },
  onTokenInput(event) { this.setData({ accessToken: event.detail.value }) },
  toggleToken() { this.setData({ showToken: !this.data.showToken }) },

  validateAndSave() {
    const apiBaseUrl = normalizeBaseUrl(this.data.apiBaseUrl)
    if (!/^https?:\/\/[^\s]+$/.test(apiBaseUrl)) {
      this.setData({ error: "API 地址必须以 http:// 或 https:// 开头" })
      return null
    }
    const value = saveRuntimeConfig({
      apiBaseUrl,
      accessToken: this.data.accessToken
    })
    const app = getApp()
    app.globalData.catalog = null
    app.globalData.catalogLoadedAt = 0
    this.setData({ ...value, error: "" })
    return value
  },

  save() {
    if (!this.validateAndSave()) return
    wx.showToast({ title: "设置已保存", icon: "success" })
  },

  testConnection() {
    if (!this.validateAndSave()) return
    this.setData({ error: "", health: null, testing: true })
    request({ path: "/health" })
      .then((health) => {
        this.setData({ health, testing: false })
        wx.showToast({ title: "连接成功", icon: "success" })
      })
      .catch((error) => this.setData({ error: error.message, testing: false }))
  },

  clear() {
    clearRuntimeConfig()
    const app = getApp()
    app.globalData.catalog = null
    this.onShow()
    wx.showToast({ title: "已恢复默认", icon: "none" })
  }
})
