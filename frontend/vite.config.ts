/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端地址可用 PORTAL_API_TARGET 覆盖（多后端并行联调时使用），默认本地 8000
const apiTarget = process.env.PORTAL_API_TARGET ?? 'http://127.0.0.1:8000'

// 开发联调（P0.5）：/api 与 /ws 代理到本地 FastAPI
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget.replace(/^http/, 'ws'), ws: true },
      // 上传图标静态托管（P2.4，豁免加密的静态资源）
      '/icons': { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
