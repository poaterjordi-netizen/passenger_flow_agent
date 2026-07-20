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
  await expect(page.getByText("Synthetic fixtures")).toBeVisible()
  await expect(page.getByText("API 运行正常")).toBeVisible()
  expect(consoleErrors).toEqual([])
})

test("bounded query returns an audited result", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("button", { name: "受约束查询" }).click()
  await page.getByRole("button", { name: "执行安全查询" }).click()
  await expect(page.getByText("查询成功")).toBeVisible()
  await expect(page.getByText("已审计")).toBeVisible()
  await expect(page.locator("table")).toBeVisible()
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
  expect(consoleErrors).toEqual([])
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
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
