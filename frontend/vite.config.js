import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Backend port for the dev-server proxy.  Reads from VITE_BACKEND_PORT env
// variable so that it works when the backend runs on a non-default port.
const backendPort = process.env.VITE_BACKEND_PORT || '8000'
const backendOrigin = `http://localhost:${backendPort}`

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': backendOrigin,
      '/ws': {
        target: backendOrigin.replace('http', 'ws'),
        ws: true,
      },
    },
  },
})
