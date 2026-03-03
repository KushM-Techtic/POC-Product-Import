import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Frontend can call /api/upload and Vite will proxy to FastAPI on :8000
      '/upload': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
