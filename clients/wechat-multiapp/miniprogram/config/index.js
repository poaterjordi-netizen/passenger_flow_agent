const STORAGE_KEY = "metroAgentRuntimeConfig"

const CLOUD_CONFIG = {
  envId: "cloud1-d0gx2d1v8c839f747",
  functionName: "metroAgentApi"
}

const DEFAULT_CONFIG = {
  transport: "synthetic",
  apiBaseUrl: "http://127.0.0.1:8000",
  accessToken: ""
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "")
}

function getRuntimeConfig() {
  const stored = wx.getStorageSync(STORAGE_KEY) || {}
  return {
    transport: stored.transport === "http" ? "http" : DEFAULT_CONFIG.transport,
    apiBaseUrl: normalizeBaseUrl(stored.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl),
    accessToken: String(stored.accessToken || "").trim(),
    cloudEnvId: CLOUD_CONFIG.envId,
    cloudFunctionName: CLOUD_CONFIG.functionName
  }
}

function saveRuntimeConfig(config) {
  const value = {
    transport: config.transport === "http" ? "http" : "synthetic",
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
  CLOUD_CONFIG,
  clearRuntimeConfig,
  getRuntimeConfig,
  normalizeBaseUrl,
  saveRuntimeConfig
}
