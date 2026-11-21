import path from 'node:path'
import { defineConfig } from 'vitest/config'

// Kept separate from vite.config.ts so the app's type-check doesn't depend on vitest's bundled vite types.
export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'], globals: false },
})
