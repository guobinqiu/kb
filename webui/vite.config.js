import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api/v1/llm': 'http://localhost:5175',
      '/api/v1/rag': 'http://localhost:5175',
      '/api/v1': 'http://localhost:5175',
      '/api/rag': 'http://localhost:5175',
      '^/health$': 'http://localhost:5175'
    }
  }
})
