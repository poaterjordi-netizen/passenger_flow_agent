import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

const apiProxy = process.env.METRO_API_PROXY || "http://127.0.0.1:8000"
const apiProxyToken = process.env.METRO_API_PROXY_TOKEN
const webPort = Number(process.env.METRO_WEB_PORT || "5173")

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "0.0.0.0",
    port: webPort,
    proxy: {
      "/api": {
        target: apiProxy,
        headers: apiProxyToken
          ? { Authorization: `Bearer ${apiProxyToken}` }
          : undefined,
      },
      "/health": apiProxy,
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
