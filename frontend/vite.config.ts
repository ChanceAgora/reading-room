import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  html: { cspNonce: '__READING_ROOM_NONCE__' },
  build: { outDir: '../src/book_library/frontend_dist', emptyOutDir: true },
  server: {
    host: '127.0.0.1',
    port: 18765,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/api', '/image', '/covers', '/static', '^/cite/[^/]+/export(?:\\?|$)'].map((path) => [
        path,
        { target: 'http://127.0.0.1:18766', changeOrigin: false },
      ]),
    ),
  },
});
