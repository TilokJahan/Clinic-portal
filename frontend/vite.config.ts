import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// /api is forwarded to the appointment service, so the browser never needs CORS.
// In Docker, nginx does the same job (see nginx.conf).
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', '').API_PROXY_TARGET || 'http://localhost:8001'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
      },
    },
  }
})
