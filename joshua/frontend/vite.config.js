import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In the container nginx proxies /api to joshua-backend (see nginx.conf), so
// the app only ever talks to its own origin. `npm run dev` on the host has no
// nginx in front of it, so the same-origin paths are proxied here instead --
// 8011 is Joshua's backend port from docker-compose.yml.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8011', changeOrigin: true },
      '/health': { target: 'http://localhost:8011', changeOrigin: true },
    },
  },
})
