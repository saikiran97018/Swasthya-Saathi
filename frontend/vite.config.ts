import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: { '/api': { target: backend, changeOrigin: true, ws: true } },
  },
  preview: {
    port: 4173,
    proxy: { '/api': { target: backend, changeOrigin: true, ws: true } },
  },
  // The Agora SDK (~1.6 MB) is its own lazy chunk, only fetched when a live call starts.
  build: { chunkSizeWarningLimit: 1700 },
})
