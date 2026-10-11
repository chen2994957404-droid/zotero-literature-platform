import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时：npm run dev（5173），接口转给后台 8780（python -m host.app.server）
// 上线：npm run build → dist/，由后台托管
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8780',
      '/files': 'http://127.0.0.1:8780',
    },
  },
})
