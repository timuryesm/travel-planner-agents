import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // CORS is already configured in src/main.py to allow localhost:5173,
    // so no proxy is needed. The API client calls http://localhost:8000 directly
    // (or whatever VITE_API_BASE_URL is set to in .env).
  },
})