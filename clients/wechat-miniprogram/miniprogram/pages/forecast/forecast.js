const { request } = require("../../utils/request")
const { COLUMN_LABELS, displayRows } = require("../../utils/format")

function nextDate(value) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

Page({
  data: {
    audit: null,
    columns: [],
    error: "",
    loading: true,
    referenceDate: "",
    resultRows: [],
    rowCount: 0,
    schemeId: "1",
    submitting: false,
    targetDate: ""
  },

  onLoad() {
    const app = getApp()
    const source = app.globalData.catalog
      ? Promise.resolve(app.globalData.catalog)
      : request({ path: "/api/v1/catalog" })
    source
      .then((catalog) => {
        app.globalData.catalog = catalog
        const referenceDate = catalog.available_dates[0]
        this.setData({
          loading: false,
          referenceDate,
          targetDate: nextDate(referenceDate)
        })
      })
      .catch((error) => this.setData({ error: error.message, loading: false }))
  },

  onReferenceDateChange(event) { this.setData({ referenceDate: event.detail.value }) },
  onTargetDateChange(event) { this.setData({ targetDate: event.detail.value }) },
  onSchemeInput(event) { this.setData({ schemeId: event.detail.value }) },

  submitForecast() {
    const schemeId = Number(this.data.schemeId)
    if (!Number.isInteger(schemeId) || schemeId < 0) {
      this.setData({ error: "方案编号必须是非负整数" })
      return
    }
    this.setData({
      audit: null,
      columns: [],
      error: "",
      resultRows: [],
      rowCount: 0,
      submitting: true
    })
    request({
      path: "/api/v1/forecasts/designated-day",
      method: "POST",
      data: {
        reference_date: this.data.referenceDate,
        target_date: this.data.targetDate,
        scheme_id: schemeId,
        limit: 1000
      }
    })
      .then((result) => {
        const ids = ["timestamp", "line_id", "station_id", "direction", "entries", "exits", "transfers"]
        const columns = ids.map((id) => ({ id, label: COLUMN_LABELS[id] || id }))
        this.setData({
          audit: result.audit,
          columns,
          resultRows: displayRows(result.rows, columns),
          rowCount: result.row_count,
          submitting: false
        })
      })
      .catch((error) => this.setData({ error: error.message, submitting: false }))
  },

  openAudit() {
    if (!this.data.audit) return
    wx.navigateTo({ url: `/pages/audit/audit?id=${this.data.audit.audit_id}` })
  }
})
