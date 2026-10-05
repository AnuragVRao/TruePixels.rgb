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
        // Overridable so a scratch API can sit behind a second dev server (e2e runs).
        target: process.env.TP_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
