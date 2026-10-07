import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Dev only: send /api to the FastAPI app (uvicorn on :8000), so the browser sees one
  // origin like in production, where FastAPI serves both the page and the API.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
