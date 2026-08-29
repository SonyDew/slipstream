import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// The dev server proxies /api to the FastAPI backend so the browser sees a
// single origin — same as production. That keeps cookies, CSRF and CORS
// behaviour identical between development and deployment.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Keep the initial payload small; charts and the admin area are lazy-loaded.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('recharts') || id.includes('d3-')) return 'charts'
            if (id.includes('react-router')) return 'router'
            // Checked before the generic react match, which would otherwise
            // swallow lucide-react and defeat the separate icon chunk.
            if (id.includes('lucide-react')) return 'icons'
            if (id.includes('react')) return 'react'
          }
        },
      },
    },
  },
})
