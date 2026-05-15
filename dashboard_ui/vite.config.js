import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Plotly wrapper is vendored locally — see
  // ``src/components/optionsViews/plotlyCreate.jsx``. The
  // ``react-plotly.js`` npm package is unusable under Rolldown 1.x
  // (Vite 8) because its Babel-compiled CJS export shape
  // (``Object.defineProperty(exports, "__esModule", {value: true}); exports["default"] = X``)
  // is not interop'd correctly — the default binding tree-shakes out,
  // causing React error #306 ("Lazy element type must resolve to a
  // class or function") at runtime.
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: '../dashboard/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Plotly is heavy (~4.5 MB). Code-split it so non-Options
        // pages never pay for the bundle. Rolldown (Vite 8) requires
        // the function form of manualChunks.
        manualChunks(id) {
          if (id.includes('plotly.js-dist-min')) {
            return 'plotly'
          }
        },
      },
    },
  },
})
