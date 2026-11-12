import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// /api is forwarded to the appointment service, so the browser never needs CORS.
// In Docker, nginx does the same job (see nginx.conf).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.API_PROXY_TARGET || 'http://localhost:8001'
  const apiMode = env.VITE_API_MODE || (mode === 'api' ? 'http' : 'mock')
  return {
    plugins: [react()],
    define: { 'import.meta.env.VITE_API_MODE': JSON.stringify(apiMode) },
    server: {
      proxy: {
        '/api': { target, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
      },
    },
  }
})
