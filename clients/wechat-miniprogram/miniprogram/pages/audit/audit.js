const { request } = require("../../utils/request")

const OPERATION_LABELS = { query: "客流查询", forecast: "指定日预测" }

Page({
  data: {
    audit: null,
    error: "",
    loading: true,
    operationLabel: ""
  },

  onLoad(options) {
    const auditId = String(options.id || "")
    if (!/^(query|forecast)-[0-9a-f]{32}$/.test(auditId)) {
      this.setData({ error: "审计编号格式无效", loading: false })
      return
    }
    request({ path: `/api/v1/audits/${auditId}` })
      .then((audit) => this.setData({
        audit,
        loading: false,
        operationLabel: OPERATION_LABELS[audit.operation] || audit.operation
      }))
      .catch((error) => this.setData({ error: error.message, loading: false }))
  },

  copyAuditId() {
    if (!this.data.audit) return
    wx.setClipboardData({ data: this.data.audit.audit_id })
  }
})
