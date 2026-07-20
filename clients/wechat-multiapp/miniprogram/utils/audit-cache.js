const PREFIX = "metroAgentAudit:"
const AUDIT_ID = /^(query|forecast)-[0-9a-f]{32}$/

function cacheAudit(audit) {
  if (!audit || !AUDIT_ID.test(String(audit.audit_id || ""))) return
  wx.setStorageSync(`${PREFIX}${audit.audit_id}`, audit)
}

function getCachedAudit(auditId) {
  if (!AUDIT_ID.test(String(auditId || ""))) return null
  const audit = wx.getStorageSync(`${PREFIX}${auditId}`)
  return audit && audit.audit_id === auditId ? audit : null
}

module.exports = { cacheAudit, getCachedAudit }
