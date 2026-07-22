const STORAGE_KEY = "metroAgentRuntimeConfig"
const CONFIG_VERSION = 2

const CLOUD_CONFIG = {
  envId: "cloud1-d0gx2d1v8c839f747",
  functionName: "metroAgentApi"
}

const DEFAULT_CONFIG = {
  transport: "http",
  apiBaseUrl: "https://metro.9m-zx.com/assistant-bridge",
  accessToken: ""
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "")
}

function getRuntimeConfig() {
  const stored = wx.getStorageSync(STORAGE_KEY) || {}
  const migrateLegacy = Number(stored.configVersion || 0) < CONFIG_VERSION
  return {
    transport: migrateLegacy
      ? DEFAULT_CONFIG.transport
      : (stored.transport === "cloudbase" ? "cloudbase" : DEFAULT_CONFIG.transport),
    apiBaseUrl: normalizeBaseUrl(
      migrateLegacy ? DEFAULT_CONFIG.apiBaseUrl : (stored.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl)
    ),
    accessToken: migrateLegacy ? "" : String(stored.accessToken || "").trim(),
    cloudEnvId: CLOUD_CONFIG.envId,
    cloudFunctionName: CLOUD_CONFIG.functionName
  }
}

function saveRuntimeConfig(config) {
  const value = {
    configVersion: CONFIG_VERSION,
    transport: config.transport === "http" ? "http" : "cloudbase",
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
