"use strict"

const { getRuntimeConfig } = require("../../config/index")
const { request } = require("../../utils/request")
const { formatCapabilities, formatRun } = require("../../utils/assistant-view")

const EXAMPLES = [
  "列出数据库中的所有地铁站",
  "给出数据库中北京地铁一号线的情况",
  "查询各站进站客流并排序",
  "奥体中心有 4 万人演唱会，预测客流并给出建议",
  "我要从北京交通大学到北京工业大学，给出合理的出行规划",
  "什么是地铁断面客流？"
]

Page({
  data: {
    capabilities: null,
    error: "",
    examples: EXAMPLES,
    history: [],
    initializing: true,
    message: EXAMPLES[0],
    result: null,
    sending: false,
    sessionId: "",
    transport: "http",
    transportLabel: "阿里云固定入口"
  },

  onLoad() {
    this.refreshRuntime()
    this.initialize(false)
  },

  onShow() {
    const previous = this.data.transport
    this.refreshRuntime()
    if (previous !== this.data.transport) {
      this.initialize(true)
      return
    }
    const sharedSessionId = getApp().globalData.assistantSessionId
    if (sharedSessionId && sharedSessionId !== this.data.sessionId) {
      this.setData({ error: "", initializing: false, sessionId: sharedSessionId })
      return
    }
    if (!this.data.sessionId && !this.data.initializing) this.initialize(false)
  },

  onPullDownRefresh() {
    this.initialize(true).finally(() => wx.stopPullDownRefresh())
  },

  refreshRuntime() {
    const config = getRuntimeConfig()
    this.setData({
      transport: config.transport,
      transportLabel: config.transport === "cloudbase"
        ? "CloudBase 备用代理"
        : "阿里云固定入口"
    })
  },

  initialize(force) {
    const app = getApp()
    const existing = !force && app.globalData.assistantSessionId
    this.setData({ error: "", initializing: true })
    // 串行完成能力发现与会话创建，便于区分固定入口、模型和会话故障。
    return request({
      path: "/api/v1/assistant/capabilities",
      timeout: 60000
    })
      .then((capabilities) => {
        const sessionRequest = existing
          ? Promise.resolve({ session_id: app.globalData.assistantSessionId })
          : request({
              path: "/api/v1/assistant/sessions",
              method: "POST",
              data: {},
              timeout: 60000
            })
        return sessionRequest.then((session) => ({ capabilities, session }))
      })
      .then(({ capabilities, session }) => {
        if (!session || !/^session-[0-9a-f]{32}$/.test(session.session_id || "")) {
          throw new Error("智能分析后端没有返回有效会话")
        }
        app.globalData.assistantSessionId = session.session_id
        this.setData({
          capabilities: formatCapabilities(capabilities),
          error: "",
          initializing: false,
          sessionId: session.session_id
        })
        return true
      })
      .catch((error) => {
        const message = this.runtimeError(error)
        app.globalData.assistantSessionId = ""
        this.setData({
          error: message,
          initializing: false,
          sessionId: ""
        })
        return false
      })
  },

  runtimeError(error) {
    const message = error && error.message ? error.message : "智能分析服务暂时不可用"
    if (this.data.transport === "cloudbase" && /未配置|unconfigured|503/.test(message)) {
      return "CloudBase 尚未配置智能体后端代理。可在设置页切换到本地调试，或由管理员配置云函数后端。"
    }
    if (
      this.data.transport === "cloudbase" &&
      /后端暂时不可用|backend_unavailable|响应超时|云端响应超时|502|504|timeout/i.test(message)
    ) {
      return "CloudBase 云函数可用，但真实智能分析后端不可达。请保持本机智能体和 HTTPS 隧道运行，并在设置页重新测试。"
    }
    if (
      this.data.transport === "http" &&
      /网络连接失败|request:fail|响应超时|502|503|504|timeout|Bad Gateway/i.test(message)
    ) {
      return "阿里云固定入口可访问，但本机智能体或受限反向隧道未就绪。请保持这台 Mac 开机联网，服务会自动重连；也可点击“重新连接”。"
    }
    return message
  },

  reconnect() {
    return this.initialize(true)
  },

  onMessageInput(event) {
    this.setData({ message: event.detail.value })
  },

  chooseQuestion(event) {
    const message = String(event.currentTarget.dataset.question || "")
    if (message) this.setData({ message })
  },

  newSession() {
    if (this.data.sending) return
    const app = getApp()
    app.globalData.assistantSessionId = ""
    this.setData({ history: [], result: null })
    this.initialize(true).then((ready) => {
      if (ready && this.data.sessionId) wx.showToast({ title: "已新建会话", icon: "success" })
    })
  },

  submit() {
    const message = String(this.data.message || "").trim()
    if (!message || this.data.sending) return
    if (message.length > 4000) {
      this.setData({ error: "问题不能超过 4000 个字符" })
      return
    }
    this.setData({ error: "", sending: true })
    const ready = this.data.sessionId
      ? Promise.resolve(this.data.sessionId)
      : this.initialize(false).then((initialized) => {
          if (!initialized) throw new Error(this.data.error || "智能分析会话未建立")
          return this.data.sessionId
        })
    ready
      .then((sessionId) => {
        if (!sessionId) throw new Error("智能分析会话未建立")
        return this.sendMessage(sessionId, message, true)
      })
      .then((run) => this.acceptRun(run))
      .catch((error) => this.setData({ error: this.runtimeError(error), sending: false }))
  },

  sendMessage(sessionId, message, mayRetrySession) {
    return request({
      path: `/api/v1/assistant/sessions/${sessionId}/messages`,
      method: "POST",
      data: { message },
      timeout: 180000
    }).catch((error) => {
      const missingSession = /404|会话(?:不存在|已失效)|session(?:[-_ ]?(?:not[-_ ]?found|expired|invalid))|unknown session/i
        .test(error.message || "")
      if (!mayRetrySession || !missingSession) throw error
      return this.initialize(true).then((ready) => {
        if (!ready || !this.data.sessionId) throw new Error(this.data.error || error.message)
        return this.sendMessage(this.data.sessionId, message, false)
      })
    })
  },

  acceptRun(run) {
    const result = formatRun(run)
    const history = [{
      runId: result.runId,
      question: result.question,
      answer: result.response.answer,
      status: result.status
    }, ...this.data.history.filter((item) => item.runId !== result.runId)].slice(0, 10)
    this.setData({ error: "", history, result, sending: false })
  },

  copyRunId() {
    if (!this.data.result) return
    wx.setClipboardData({ data: this.data.result.runId })
  },

  copyExternalLink(event) {
    const url = String(event.currentTarget.dataset.url || "")
    if (!url.startsWith("https://")) return
    wx.setClipboardData({
      data: url,
      success() { wx.showToast({ title: "链接已复制", icon: "success" }) }
    })
  },

  openSettings() {
    wx.switchTab({ url: "/pages/settings/settings" })
  }
})
