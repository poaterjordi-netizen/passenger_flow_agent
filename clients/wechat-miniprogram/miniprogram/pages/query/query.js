const { request } = require("../../utils/request")
const { cacheAudit } = require("../../utils/audit-cache")
const { chartBars, columnsForResult, displayRows } = require("../../utils/format")

function splitDateTime(value) {
  const normalized = String(value || "")
  return { date: normalized.slice(0, 10), time: normalized.slice(11, 16) }
}

Page({
  data: {
    allowedDimensions: [],
    audit: null,
    bars: [],
    catalog: null,
    columns: [],
    directionIndex: 0,
    directionOptions: [{ id: "", label: "全部方向" }],
    endDate: "",
    endTime: "",
    error: "",
    lineIndex: 0,
    lineOptions: ["全部线路"],
    loading: true,
    metricIndex: 0,
    metricLabels: [],
    resultRows: [],
    rowCount: 0,
    stationIndex: 0,
    stationOptions: ["全部车站"],
    startDate: "",
    startTime: "",
    submitting: false
  },

  onLoad() {
    this.loadCatalog()
  },

  loadCatalog() {
    const app = getApp()
    const source = app.globalData.catalog
      ? Promise.resolve(app.globalData.catalog)
      : request({ path: "/api/v1/catalog" })
    source
      .then((catalog) => {
        app.globalData.catalog = catalog
        const start = splitDateTime(catalog.default_time_range.start)
        const end = splitDateTime(catalog.default_time_range.end)
        this.setData({
          catalog,
          directionOptions: [{ id: "", label: "全部方向" }, ...catalog.directions],
          endDate: end.date,
          endTime: end.time,
          lineOptions: ["全部线路", ...catalog.lines],
          loading: false,
          metricLabels: catalog.metrics.map((metric) => metric.label),
          startDate: start.date,
          startTime: start.time,
          stationOptions: ["全部车站", ...catalog.stations]
        })
        this.updateAllowedDimensions(0)
      })
      .catch((error) => this.setData({ error: error.message, loading: false }))
  },

  updateAllowedDimensions(metricIndex) {
    const metric = this.data.catalog.metrics[metricIndex]
    const labelMap = {}
    this.data.catalog.dimensions.forEach((item) => { labelMap[item.id] = item.label })
    this.setData({
      allowedDimensions: metric.dimensions.map((id) => ({ id, label: labelMap[id], checked: false }))
    })
  },

  onMetricChange(event) {
    const metricIndex = Number(event.detail.value)
    this.setData({ metricIndex })
    this.updateAllowedDimensions(metricIndex)
  },

  onDimensionsChange(event) {
    const selected = event.detail.value
    this.setData({
      allowedDimensions: this.data.allowedDimensions.map((item) => ({
        ...item,
        checked: selected.includes(item.id)
      }))
    })
  },

  onLineChange(event) { this.setData({ lineIndex: Number(event.detail.value) }) },
  onStationChange(event) { this.setData({ stationIndex: Number(event.detail.value) }) },
  onDirectionChange(event) { this.setData({ directionIndex: Number(event.detail.value) }) },
  onStartDateChange(event) { this.setData({ startDate: event.detail.value }) },
  onStartTimeChange(event) { this.setData({ startTime: event.detail.value }) },
  onEndDateChange(event) { this.setData({ endDate: event.detail.value }) },
  onEndTimeChange(event) { this.setData({ endTime: event.detail.value }) },

  submitQuery() {
    const metric = this.data.catalog.metrics[this.data.metricIndex]
    const filters = []
    if (this.data.lineIndex) {
      filters.push({ field: "line_id", operator: "eq", value: this.data.lineOptions[this.data.lineIndex] })
    }
    if (this.data.stationIndex) {
      filters.push({ field: "station_id", operator: "eq", value: this.data.stationOptions[this.data.stationIndex] })
    }
    if (this.data.directionIndex) {
      filters.push({
        field: "direction",
        operator: "eq",
        value: this.data.directionOptions[this.data.directionIndex].id
      })
    }
    const dimensions = this.data.allowedDimensions.filter((item) => item.checked).map((item) => item.id)
    const payload = {
      city: this.data.catalog.city || undefined,
      metric: metric.id,
      source_version: this.data.catalog.source_version || undefined,
      time_range: {
        start: `${this.data.startDate}T${this.data.startTime}:00+08:00`,
        end: `${this.data.endDate}T${this.data.endTime}:00+08:00`
      },
      dimensions,
      filters,
      limit: 100
    }
    this.setData({
      audit: null,
      bars: [],
      columns: [],
      error: "",
      resultRows: [],
      rowCount: 0,
      submitting: true
    })
    request({ path: "/api/v1/queries", method: "POST", data: payload })
      .then((result) => {
        cacheAudit(result.audit)
        const columns = columnsForResult(result.dimensions, result.metric)
        this.setData({
          audit: result.audit,
          bars: chartBars(result.rows, result.dimensions[0], result.metric),
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
