import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'

export default defineConfig({
  plugins: [
    vue({ template: { transformAssetUrls } }),
    quasar({ sassVariables: fileURLToPath(new URL('./src/css/quasar-variables.scss', import.meta.url)) }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 9000,
    // Запросы к API уходят на Django: один адрес для браузера, без настроек CORS.
    proxy: {
      '/api': process.env.VITE_API_TARGET || 'http://localhost:8000',
    },
  },
})
