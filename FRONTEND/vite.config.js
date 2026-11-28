import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // /api ile başlayan istekler Ranya'nın FastAPI backend'ine yönlendirilir.
    // Böylece tarayıcı farklı adres (CORS) engeline takılmaz.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
