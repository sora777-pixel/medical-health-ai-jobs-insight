import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [inspectAttr(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // 本地同时运行 `python -m jobsinsight serve --no-scheduler` 时，
    // 自动化面板可直接调用后端；后端未启动时数据客户端会回退到 public/data。
    proxy: {
      "/api": "http://127.0.0.1:8787",
    },
  },
});
