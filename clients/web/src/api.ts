import { client } from "./client/client.gen"
import {
  assistantMessageApiV1AssistantSessionsSessionIdMessagesPost,
  auditApiV1AuditsAuditIdGet,
  catalogApiV1CatalogGet,
  createAssistantSessionApiV1AssistantSessionsPost,
  forecastApiV1ForecastsDesignatedDayPost,
  healthHealthGet,
  queryApiV1QueriesPost,
} from "./client/sdk.gen"
import type { ForecastRequest, QueryRequest } from "./client/types.gen"

client.setConfig({ baseUrl: import.meta.env.VITE_API_URL || "" })

function unwrap<T>(response: { data?: T; error?: unknown }): T {
  if (response.error) {
    const message =
      typeof response.error === "object" &&
      response.error !== null &&
      "detail" in response.error
        ? JSON.stringify(response.error)
        : "请求失败，请检查后端服务和查询范围"
    throw new Error(message)
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

export async function sendAssistantMessage(sessionId: string, message: string) {
  return unwrap(
    await assistantMessageApiV1AssistantSessionsSessionIdMessagesPost({
      path: { session_id: sessionId },
      body: { message },
    }),
  )
}
