import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

const apiProxy = process.env.METRO_API_PROXY || "http://127.0.0.1:8000"
const apiProxyToken = process.env.METRO_API_PROXY_TOKEN
const webPort = Number(process.env.METRO_WEB_PORT || "5173")
const webBasePath = normalizeBasePath(process.env.METRO_WEB_BASE_PATH || "/")
const webBasePrefix = webBasePath === "/" ? "" : webBasePath.slice(0, -1)

function normalizeBasePath(value: string) {
  const trimmed = value.trim()
  if (!trimmed || trimmed === "/") return "/"
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}/`
}

const apiProxyOptions = {
  target: apiProxy,
  headers: apiProxyToken
    ? { Authorization: `Bearer ${apiProxyToken}` }
    : undefined,
}
const baseAwareProxy = webBasePrefix
  ? {
      [`${webBasePrefix}/api`]: {
        ...apiProxyOptions,
        rewrite: (path: string) => path.slice(webBasePrefix.length),
      },
      [`${webBasePrefix}/health`]: {
        target: apiProxy,
        rewrite: (path: string) => path.slice(webBasePrefix.length),
      },
    }
  : {}

export default defineConfig({
  base: webBasePath,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "0.0.0.0",
    port: webPort,
    allowedHosts: ["localhost", "127.0.0.1", "metro.9m-zx.com"],
    proxy: {
      "/api": apiProxyOptions,
      "/health": apiProxy,
      ...baseAwareProxy,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: webPort,
    strictPort: true,
    allowedHosts: ["localhost", "127.0.0.1", "metro.9m-zx.com"],
    proxy: {
      "/api": apiProxyOptions,
      "/health": apiProxy,
      ...baseAwareProxy,
    },
  },
  build: {
    // ECharts is isolated behind React.lazy; its gzip output stays below 200 kB.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: [
            "echarts/core",
            "echarts/charts",
            "echarts/components",
            "echarts/renderers",
          ],
          query: ["@tanstack/react-query"],
          react: ["react", "react-dom"],
        },
      },
    },
  },
})
