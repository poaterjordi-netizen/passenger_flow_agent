const { request } = require("../../utils/request")
const { formatNumber } = require("../../utils/format")

Page({
  data: {
    cards: [],
    error: "",
    loading: true,
    rangeText: "",
    topStations: []
  },

  onLoad() {
    this.loadDashboard()
  },

  onPullDownRefresh() {
    this.loadDashboard(true).finally(() => wx.stopPullDownRefresh())
  },

  loadCatalog(force) {
    const app = getApp()
    if (!force && app.globalData.catalog) return Promise.resolve(app.globalData.catalog)
    return request({ path: "/api/v1/catalog" }).then((catalog) => {
      app.globalData.catalog = catalog
      app.globalData.catalogLoadedAt = Date.now()
      return catalog
    })
  },

  loadDashboard(force) {
    this.setData({ error: "", loading: true })
    return this.loadCatalog(force)
      .then((catalog) => {
        const timeRange = catalog.default_time_range
        const metricQueries = catalog.metrics.map((metric) =>
          request({
            path: "/api/v1/queries",
            method: "POST",
            data: {
              metric: metric.id,
              time_range: timeRange,
              dimensions: [],
              filters: [],
              limit: 10
            }
          }).then((result) => ({
            id: metric.id,
            label: metric.label,
            value: formatNumber(result.rows.length ? result.rows[0][metric.id] : 0),
            unit: "人次"
          }))
        )
        const stationQuery = request({
          path: "/api/v1/queries",
          method: "POST",
          data: {
            metric: "entries",
            time_range: timeRange,
            dimensions: ["station"],
            filters: [],
            limit: 100
          }
        })
        return Promise.all([Promise.all(metricQueries), stationQuery, catalog])
      })
      .then(([cards, stationResult, catalog]) => {
        const topStations = stationResult.rows
          .slice()
          .sort((left, right) => Number(right.entries) - Number(left.entries))
          .slice(0, 5)
          .map((row, index) => ({
            rank: index + 1,
            station: row.station,
            value: formatNumber(row.entries)
          }))
        const range = catalog.default_time_range
        this.setData({
          cards,
          loading: false,
          rangeText: `${range.start.slice(0, 16).replace("T", " ")} — ${range.end.slice(11, 16)}`,
          topStations
        })
      })
      .catch((error) => {
        this.setData({ error: error.message, loading: false })
      })
  },

  openQuery() {
    wx.switchTab({ url: "/pages/query/query" })
  },

  openForecast() {
    wx.switchTab({ url: "/pages/forecast/forecast" })
  },

  openSettings() {
    wx.switchTab({ url: "/pages/settings/settings" })
  }
})
