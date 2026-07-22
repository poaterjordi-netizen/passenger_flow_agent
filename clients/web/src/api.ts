import { client } from "./client/client.gen"
import {
  assistantCapabilitiesApiV1AssistantCapabilitiesGet,
  assistantMessageApiV1AssistantSessionsSessionIdMessagesPost,
  auditApiV1AuditsAuditIdGet,
  catalogApiV1CatalogGet,
  createAssistantSessionApiV1AssistantSessionsPost,
  forecastApiV1ForecastsDesignatedDayPost,
  governanceStatusApiV1GovernanceStatusGet,
  healthHealthGet,
  queryApiV1QueriesPost,
} from "./client/sdk.gen"
import type { ForecastRequest, QueryRequest } from "./client/types.gen"

client.setConfig({ baseUrl: import.meta.env.VITE_API_URL || "" })

const configuredAssistantTimeout = Number(
  import.meta.env.VITE_ASSISTANT_TIMEOUT_MS || "30000",
)
const assistantTimeoutMs =
  Number.isFinite(configuredAssistantTimeout) &&
  configuredAssistantTimeout >= 1_000 &&
  configuredAssistantTimeout <= 300_000
    ? configuredAssistantTimeout
    : 30_000

function unwrap<T>(response: { data?: T; error?: unknown }): T {
  if (response.error) {
    const code =
      typeof response.error === "object" &&
      response.error !== null &&
      "error" in response.error &&
      typeof response.error.error === "object" &&
      response.error.error !== null &&
      "code" in response.error.error
        ? String(response.error.error.code)
        : null
    const safeMessages: Record<string, string> = {
      invalid_request: "请求未通过安全校验，请缩小范围或调整问题后重试",
      provider_failure:
        "模型服务调用失败，本次没有绕过 verifier 或自动切换 Provider",
      forbidden: "当前身份、数据范围或治理门禁不允许执行此操作",
    }
    throw new Error(
      (code && safeMessages[code]) || "请求失败，请检查后端服务和查询范围",
    )
  }
  if (!response.data) throw new Error("服务未返回数据")
  return response.data
}

export async function getHealth() {
  return unwrap(await healthHealthGet())
}

export async function getCatalog() {
  return unwrap(await catalogApiV1CatalogGet())
}

export async function getGovernanceStatus() {
  return unwrap(await governanceStatusApiV1GovernanceStatusGet())
}

export async function runQuery(body: QueryRequest) {
  return unwrap(await queryApiV1QueriesPost({ body }))
}

export async function runForecast(body: ForecastRequest) {
  return unwrap(await forecastApiV1ForecastsDesignatedDayPost({ body }))
}

export async function getAudit(auditId: string) {
  return unwrap(
    await auditApiV1AuditsAuditIdGet({ path: { audit_id: auditId } }),
  )
}

export async function createAssistantSession() {
  return unwrap(await createAssistantSessionApiV1AssistantSessionsPost())
}

export async function getAssistantCapabilities() {
  return unwrap(await assistantCapabilitiesApiV1AssistantCapabilitiesGet())
}

export async function sendAssistantMessage(sessionId: string, message: string) {
  const controller = new AbortController()
  const timeout = window.setTimeout(
    () => controller.abort(),
    assistantTimeoutMs,
  )
  try {
    return unwrap(
      await assistantMessageApiV1AssistantSessionsSessionIdMessagesPost({
        path: { session_id: sessionId },
        body: { message },
        signal: controller.signal,
      }),
    )
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(
        `分析请求已在 ${Math.round(assistantTimeoutMs / 1_000)} 秒后停止；后端可能仍在收尾，请稍后重试`,
      )
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}
