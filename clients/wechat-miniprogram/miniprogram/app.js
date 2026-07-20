const { CLOUD_CONFIG } = require("./config/index")

App({
  onLaunch() {
    if (!wx.cloud) {
      console.error("当前微信基础库不支持云开发")
      return
    }
    wx.cloud.init({
      env: CLOUD_CONFIG.envId,
      traceUser: true
    })
  },

  globalData: {
    catalog: null,
    catalogLoadedAt: 0
  }
})
