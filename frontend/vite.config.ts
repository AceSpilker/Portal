/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import { VitePWA } from 'vite-plugin-pwa'

// 后端地址可用 PORTAL_API_TARGET 覆盖（多后端并行联调时使用），默认本地 8000
const apiTarget = process.env.PORTAL_API_TARGET ?? 'http://127.0.0.1:8000'

// 开发联调（P0.5）：/api 与 /ws 代理到本地 FastAPI
export default defineConfig({
  plugins: [
    vue(),
    // PWA（M16-2/4；P17.4）：桌面浏览器安装场景；dev 不注入 SW 以免缓存干扰联调
    VitePWA({
      devOptions: { enabled: false },
      registerType: 'autoUpdate',
      manifest: {
        name: 'Portal',
        short_name: 'Portal',
        description: 'Self-hosted NAS Portal',
        theme_color: '#4f6ef7',
        background_color: '#0f172a',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // 主 bundle 含 ECharts/Element 全量，>2MB 默认上限会导致预缓存清单缺失报错
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        navigateFallback: '/',
        // API/WS 不缓存（数据实时性优先）
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//, /^\/files\//, /^\/icons\//],
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget.replace(/^http/, 'ws'), ws: true },
      // 上传图标静态托管（P2.4，豁免加密的静态资源）
      '/icons': { target: apiTarget, changeOrigin: true },
      // SSH 隧道反代直达（P20.2，豁免加密的签名直链）
      '/tunnel': { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
