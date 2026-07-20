const STORAGE_KEY = "metroAgentRuntimeConfig"

const DEFAULT_CONFIG = {
  apiBaseUrl: "http://127.0.0.1:8000",
  accessToken: ""
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "")
}

function getRuntimeConfig() {
  const stored = wx.getStorageSync(STORAGE_KEY) || {}
  return {
    apiBaseUrl: normalizeBaseUrl(stored.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl),
    accessToken: String(stored.accessToken || "").trim()
  }
}

function saveRuntimeConfig(config) {
  const value = {
    apiBaseUrl: normalizeBaseUrl(config.apiBaseUrl),
    accessToken: String(config.accessToken || "").trim()
  }
  wx.setStorageSync(STORAGE_KEY, value)
  return value
}

function clearRuntimeConfig() {
  wx.removeStorageSync(STORAGE_KEY)
}

module.exports = {
  clearRuntimeConfig,
  getRuntimeConfig,
  normalizeBaseUrl,
  saveRuntimeConfig
}
