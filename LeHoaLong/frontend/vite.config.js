import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The team's shared stylesheet lives at <repo root>/shared/styles.css, outside
// this project. Vite's dev server refuses to serve files above its root unless
// they are allow-listed, so name it here; the Docker build reproduces the same
// relative layout (see Dockerfile) so one import path works in both.
const sharedDir = fileURLToPath(new URL('../../shared', import.meta.url))

// In the container nginx proxies /api and /health to the backend, so the app
// only ever talks to its own origin. `npm run dev` and `npm run preview` have
// no nginx in front of them, so the same paths are proxied here instead.
const apiProxy = {
  '/api': { target: 'http://localhost:8061', changeOrigin: true },
  '/health': { target: 'http://localhost:8061', changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  server: {
    // 8060 is Le Hoa Long's frontend port from docker-compose.yml. The dev
    // server uses it too so there is one number to remember.
    port: 8060,
    fs: { allow: ['.', sharedDir] },
    proxy: apiProxy,
  },
  // `npm run preview` serves the production build. It needs the same proxy,
  // otherwise checking the built bundle against a running backend is
  // impossible without standing up nginx.
  preview: {
    port: 8060,
    proxy: apiProxy,
  },
})
