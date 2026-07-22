const { CLOUD_CONFIG } = require("./config/index")

App({
  onLaunch() {
    if (!wx.cloud) {
      return
    }
    wx.cloud.init({
      env: CLOUD_CONFIG.envId,
      traceUser: true
    })
  },

  globalData: {
    assistantSessionId: "",
    catalog: null,
    catalogLoadedAt: 0
  }
})
