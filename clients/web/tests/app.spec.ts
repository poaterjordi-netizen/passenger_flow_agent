import { expect, test } from "@playwright/test"

test("dashboard loads governed passenger flow data", async ({ page }) => {
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })
  await page.goto("/")
  await expect(
    page.getByRole("heading", { name: "地铁客流运营总览" }),
  ).toBeVisible()
  await expect(page.getByText("进站客流")).toBeVisible()
  await expect(page.getByText("synthetic", { exact: true })).toBeVisible()
  await expect(
    page.getByText("Synthetic environment", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("API 运行正常")).toBeVisible()
  expect(consoleErrors).toEqual([])
})

test("bounded query returns an audited result", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "受约束查询" }).click()
  await page.getByRole("button", { name: "执行安全查询" }).click()
  await expect(page.getByText("查询成功")).toBeVisible()
  await expect(page.getByText("结果完整")).toBeVisible()
  await expect(
    page.getByText("local-synthetic-policy-v1", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("已审计")).toBeVisible()
  await expect(page.locator("table")).toBeVisible()
})

test("system page renders backend governance, scope, and promotion state", async ({
  page,
}) => {
  await page.goto("/")
  await page.getByRole("button", { name: "系统状态" }).click()
  await expect(page.getByText("实际生效的治理状态")).toBeVisible()
  await expect(
    page.getByText("Subject：local-synthetic-user", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("源版本：synthetic-v1")).toBeVisible()
  await expect(page.getByText("注册质量：pass", { exact: false })).toBeVisible()
  await expect(page.getByText("运行质量：pass", { exact: false })).toBeVisible()
  await expect(
    page.getByText("单主体静态令牌适配器", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("production-readonly-promotion-v1")).toBeVisible()
  await expect(page.getByText("门禁状态尚未批准")).toBeVisible()
  await page.getByText(/查看实际注册工具/).click()
  await expect(page.getByText("query_metric", { exact: true })).toBeVisible()
})

test("assistant UI obeys a backend promotion block and does not create a session", async ({
  page,
}) => {
  let sessionRequests = 0
  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/assistant/sessions"))
      sessionRequests += 1
  })
  await page.route("**/api/v1/governance/status", async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.data_scope = "production-shadow"
    payload.assistant_enabled = false
    payload.assistant_status = "blocked_by_promotion_gate"
    payload.promotion.enforced = true
    await route.fulfill({ response, json: payload })
  })
  await page.goto("/")
  await expect(
    page.getByText("Real MySQL · Local shadow", { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "智能分析" }).click()
  await expect(
    page.getByText("大型活动问题会调用真实客流上下文", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("Promotion 门禁未通过").first()).toBeVisible()
  await expect(
    page.getByRole("button", { name: "治理门禁已阻断" }),
  ).toBeDisabled()
  await expect(
    page.getByRole("textbox", { name: "自然语言任务" }),
  ).toBeDisabled()
  expect(sessionRequests).toBe(0)
})

test("forecast is explicitly labelled as a baseline", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "基线预测" }).click()
  await expect(page.getByText("非 ML 模型")).toBeVisible()
  await page.getByRole("button", { name: "生成预测预览" }).click()
  await expect(
    page.getByText("reference_day_copy", { exact: true }),
  ).toBeVisible()
})

test("assistant shows a verified plan, evidence, and trajectory", async ({
  page,
}) => {
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await expect(
    page.getByRole("heading", { name: "地铁客流智能分析" }),
  ).toBeVisible()
  await expect(page.getByText("当前运行：离线确定性基线")).toBeVisible()
  await expect(
    page.getByText("真实 GPT-5.6-sol shadow", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("3/3", { exact: true })).toBeVisible()
  await expect(page.getByText("大模型不保存客流事实")).toBeVisible()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("Evidence verified")).toBeVisible()
  await expect(
    page.getByText("query_metric", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("arguments:", { exact: false }).first(),
  ).toBeVisible()
  await expect(page.getByText("状态机时间线")).toBeVisible()
  await expect(page.getByText("Evidence Packet")).toBeVisible()
  await expect(page.getByText("工具结果图表")).toBeVisible()
  await expect(page.locator("table.data-table")).toBeVisible()
  await expect(page.getByText("RESPOND", { exact: true })).toBeVisible()
  await expect(page.getByText("未配置真实模型")).toBeVisible()
  await expect(page.getByText("无模型调用")).toBeVisible()
  await expect(page.getByText("确定性 verifier 已通过")).toBeVisible()
  expect(consoleErrors).toEqual([])
})

test("assistant distinguishes configured models from actual calls and reports usage", async ({
  page,
}) => {
  await page.route("**/api/v1/assistant/capabilities", async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.active_runtime = {
      ...payload.active_runtime,
      provider: "openai-compatible:test-model",
      model: "test-model",
      mode: "openai_compatible",
      real_model_configured: true,
      real_model_active: false,
      invocation_status: "configured",
      usage_reporting: "unavailable",
    }
    await route.fulfill({ response, json: payload })
  })
  await page.route("**/api/v1/assistant/sessions/*/messages", async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.provider = "openai-compatible:test-model"
    payload.model_runtime = {
      provider: "openai-compatible:test-model",
      model: "test-model",
      mode: "openai_compatible",
      real_model_configured: true,
      real_model_active: true,
      invocation_status: "succeeded",
      usage_reporting: "complete",
      provider_calls: 3,
      model_calls: 3,
      input_tokens: 300,
      output_tokens: 90,
      reasoning_tokens: 30,
      total_tokens: 390,
      elapsed_seconds: 1.25,
    }
    payload.model_egress = [
      {
        call_id: "model-call-test",
        purpose: "synthesis",
        decision: "approved",
        endpoint_policy_id: "test-policy",
        provider: "openai-compatible:test-model",
        model: "test-model",
        endpoint_target_hash: "a".repeat(64),
        endpoint_binding_verified: true,
        exact_payload_hash: "b".repeat(64),
        outbound_field_paths: ["evidence.facts", "question"],
        started_at: "2026-07-21T00:00:00Z",
        completed_at: "2026-07-21T00:00:01Z",
        status: "succeeded",
      },
    ]
    await route.fulfill({ response, json: payload })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await expect(page.getByText("已配置：test-model（尚未调用）")).toBeVisible()
  await expect(
    page.getByText("真实模型已配置，尚未代表本次已调用"),
  ).toBeVisible()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("3 次实际 API 调用")).toBeVisible()
  await expect(page.getByText("390 tokens · 1.25s")).toBeVisible()
  await expect(page.getByText("输入 300 · 输出 90 · 推理 30")).toBeVisible()
  await expect(page.getByText("1 次 · 1 次批准")).toBeVisible()
  await page.getByText("调用级模型出域审计（1）").click()
  await expect(page.getByText("synthesis · approved · succeeded")).toBeVisible()
  await expect(page.getByText("端点绑定：已核验")).toBeVisible()
})

test("forecast renders only metrics returned by the authorized response", async ({
  page,
}) => {
  await page.route("**/api/v1/forecasts/designated-day", async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.rows = payload.rows.map(
      ({
        entries: _entries,
        transfers: _transfers,
        ...row
      }: Record<string, unknown>) => row,
    )
    await route.fulfill({ response, json: payload })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "基线预测" }).click()
  await page.getByRole("button", { name: "生成预测预览" }).click()
  await expect(
    page.getByRole("columnheader", { name: "出站客流" }),
  ).toBeVisible()
  await expect(
    page.getByRole("columnheader", { name: "进站客流" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("columnheader", { name: "换乘客流" }),
  ).toHaveCount(0)
})

test("assistant keeps the form usable when capability discovery fails", async ({
  page,
}) => {
  await page.route("**/api/v1/assistant/capabilities", (route) =>
    route.abort("failed"),
  )
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await expect(page.getByText("运行时状态未知")).toBeVisible()
  await expect(page.getByText("重新读取运行能力")).toBeVisible()
  await expect(
    page.getByRole("textbox", { name: "自然语言任务" }),
  ).toBeEnabled()
  await expect(page.getByRole("button", { name: "开始智能分析" })).toBeEnabled()
})

test("assistant does not mislabel a pending capability request as offline", async ({
  page,
}) => {
  await page.route("**/api/v1/assistant/capabilities", async (route) => {
    const response = await route.fetch()
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({ response })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await expect(page.getByText("正在检测运行时")).toBeVisible()
  await expect(page.getByText("当前运行：离线确定性基线")).toBeVisible()
})

test("assistant marks failed verification as forbidden and hides recommendations", async ({
  page,
}) => {
  await page.route("**/api/v1/assistant/sessions/*/messages", async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.verification = {
      ...payload.verification,
      valid: false,
      errors: [
        "response contains numbers without cited semantic evidence: 999",
      ],
    }
    payload.response.recommendations = ["关闭车站"]
    await route.fulfill({ response, json: payload })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("核验失败 · 禁止采纳")).toBeVisible()
  await expect(page.getByText("核验失败：禁止采纳")).toBeVisible()
  await expect(page.getByText("未核验回答（禁止采纳）")).toBeVisible()
  await expect(
    page.getByText(
      "response contains numbers without cited semantic evidence: 999",
    ),
  ).toBeVisible()
  await expect(
    page.getByText("未核验处置建议已隐藏，禁止执行或采纳。"),
  ).toBeVisible()
  await expect(page.getByText("关闭车站")).toHaveCount(0)
  await expect(page.getByText("Evidence verified")).toHaveCount(0)
})

test("assistant redacts backend details from provider failures", async ({
  page,
}) => {
  await page.route("**/api/v1/assistant/sessions/*/messages", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "provider_failure",
          message: "secret token and /private/backend/path",
        },
      }),
    }),
  )
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByRole("alert")).toContainText("模型服务调用失败")
  await expect(page.getByText(/secret token|private\/backend/)).toHaveCount(0)
})

test("assistant keeps a conversation and applies a follow-up", async ({
  page,
}) => {
  await page.goto("/")
  await page.getByRole("button", { name: "智能分析" }).click()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("Evidence verified")).toBeVisible()
  await page.getByRole("textbox", { name: "自然语言任务" }).fill("只看前三名")
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("用户：只看前三名")).toBeVisible()
  await expect(
    page.getByText("rank_stations", { exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByText("Evidence verified")).toBeVisible()
})

test("assistant remains usable without horizontal overflow on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await page.getByRole("button", { name: "打开导航" }).click()
  await page.getByRole("button", { name: "智能分析" }).click()
  await page.getByRole("button", { name: "开始智能分析" }).click()
  await expect(page.getByText("Evidence verified")).toBeVisible()
  const regularLayout = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    outliers: [...document.querySelectorAll("body *")]
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          tag: element.tagName,
          text: element.textContent?.trim().slice(0, 80) ?? "",
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        }
      })
      .filter(
        (element) => element.width > 0 && element.right > window.innerWidth + 1,
      )
      .slice(0, 10),
  }))
  expect(
    regularLayout.overflow,
    JSON.stringify(regularLayout.outliers),
  ).toBeLessThanOrEqual(0)
  await page.setViewportSize({ width: 320, height: 568 })
  const narrowLayout = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    outliers: [...document.querySelectorAll("body *")]
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          tag: element.tagName,
          text: element.textContent?.trim().slice(0, 80) ?? "",
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        }
      })
      .filter(
        (element) => element.width > 0 && element.right > window.innerWidth + 1,
      )
      .slice(0, 10),
  }))
  expect(
    narrowLayout.overflow,
    JSON.stringify(narrowLayout.outliers),
  ).toBeLessThanOrEqual(0)
})
