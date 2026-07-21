import { existsSync } from "node:fs"
import { defineConfig, devices } from "@playwright/test"

const backendCommand = existsSync("../../.venv/bin/python")
  ? "../../.venv/bin/python -m metro_agent.api"
  : "python -m metro_agent.api"
const backendPort = Number(process.env.METRO_E2E_API_PORT || "8000")
const webPort = Number(process.env.METRO_E2E_WEB_PORT || "5173")
const backendUrl = `http://127.0.0.1:${backendPort}`
const webUrl = `http://127.0.0.1:${webPort}`

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `METRO_API_PORT=${backendPort} ${backendCommand}`,
      cwd: ".",
      url: `${backendUrl}/health`,
      reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVERS === "1",
    },
    {
      command: `METRO_WEB_PORT=${webPort} METRO_API_PROXY=${backendUrl} npm run dev -- --host 127.0.0.1`,
      cwd: ".",
      url: webUrl,
      reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVERS === "1",
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
