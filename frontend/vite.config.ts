import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    // Phase 6: never inline assets as data: URIs - the CSP allows fonts and
    // scripts from 'self' only (img-src also allows data:, fonts do not).
    assetsInlineLimit: 0,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
