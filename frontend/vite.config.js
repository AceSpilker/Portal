/// <reference types="vitest" />
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
// 开发联调（P0.5）：/api 与 /ws 代理到本地 FastAPI
export default defineConfig({
    plugins: [vue()],
    server: {
        port: 5173,
        proxy: {
            '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
            '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
        },
    },
    test: {
        environment: 'jsdom',
    },
});
