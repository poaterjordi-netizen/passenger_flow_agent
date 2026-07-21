import { existsSync } from "node:fs"
import { defineConfig, devices } from "@playwright/test"

const backendCommand = existsSync("../../.venv/bin/python")
  ? "../../.venv/bin/python -m metro_agent.api"
  : "python -m metro_agent.api"

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: backendCommand,
      cwd: ".",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVERS === "1",
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: ".",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVERS === "1",
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
