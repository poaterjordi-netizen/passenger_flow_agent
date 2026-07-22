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
    cloudEnvId: "",
    cloudFunctionName: "",
    error: "",
    health: null,
    assistantReady: false,
    showToken: false,
    testing: false,
    transport: "http"
  },

  onShow() {
    const config = getRuntimeConfig()
    this.setData({
      accessToken: config.accessToken,
      apiBaseUrl: config.apiBaseUrl,
      cloudEnvId: config.cloudEnvId,
      cloudFunctionName: config.cloudFunctionName,
      error: "",
      health: null,
      assistantReady: false,
      transport: config.transport
    })
  },

  onBaseUrlInput(event) { this.setData({ apiBaseUrl: event.detail.value }) },
  onTokenInput(event) { this.setData({ accessToken: event.detail.value }) },
  toggleToken() { this.setData({ showToken: !this.data.showToken }) },
  useCloudbase() { this.setData({ transport: "cloudbase", error: "", health: null }) },
  useHttp() {
    this.setData({
      transport: "http",
      apiBaseUrl: this.data.apiBaseUrl || "https://metro.9m-zx.com/assistant-bridge",
      error: "",
      health: null
    })
  },

  validateAndSave() {
    const apiBaseUrl = normalizeBaseUrl(this.data.apiBaseUrl)
    if (this.data.transport === "http" && !/^https?:\/\/[^\s]+$/.test(apiBaseUrl)) {
      this.setData({ error: "API 地址必须以 http:// 或 https:// 开头" })
      return null
    }
    const value = saveRuntimeConfig({
      transport: this.data.transport,
      apiBaseUrl,
      accessToken: this.data.accessToken
    })
    const app = getApp()
    app.globalData.assistantSessionId = ""
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
    this.setData({ assistantReady: false, error: "", health: null, testing: true })
    request({ path: "/health", timeout: 15000 })
      .then((health) => {
        const proxy = health && health.assistant_proxy
        this.setData({ health: { ...health, assistant_ready: false } })
        if (this.data.transport === "cloudbase" && proxy && proxy.configured === false) {
          throw new Error("CloudBase 已连接，但智能分析后端尚未配置")
        }
        if (this.data.transport === "cloudbase" && proxy && proxy.reachable === false) {
          throw new Error("CloudBase 已连接，但真实智能分析后端不可达；请保持本机智能体和 HTTPS 隧道运行")
        }
        // 握手按“能力目录 -> 会话”顺序执行，避免只验证健康接口却没有
        // 建立真实智能分析会话。
        return request({ path: "/api/v1/assistant/capabilities", timeout: 55000 })
          .then((capabilities) => request({
            path: "/api/v1/assistant/sessions",
            method: "POST",
            data: {},
            timeout: 55000
          }).then((session) => ({ health, capabilities, session })))
      })
      .then(({ health, capabilities, session }) => {
        if (!session || !/^session-[0-9a-f]{32}$/.test(session.session_id || "")) {
          throw new Error("智能分析后端没有返回有效会话")
        }
        const app = getApp()
        app.globalData.assistantSessionId = session.session_id
        const runtime = capabilities.active_runtime || {}
        this.setData({
          assistantReady: true,
          error: "",
          health: {
            ...health,
            assistant_ready: true,
            assistant_session_id: session.session_id,
            assistant_model: runtime.model || "未报告",
            assistant_data_scope: capabilities.data_scope || "未报告"
          },
          testing: false
        })
        wx.showToast({ title: "智能分析可用", icon: "success" })
      })
      .catch((error) => this.setData({ assistantReady: false, error: error.message, testing: false }))
  },

  clear() {
    clearRuntimeConfig()
    const app = getApp()
    app.globalData.assistantSessionId = ""
    app.globalData.catalog = null
    this.onShow()
    wx.showToast({ title: "已恢复默认", icon: "none" })
  }
})
