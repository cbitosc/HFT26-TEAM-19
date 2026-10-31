import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Loopback only by default. For phone access over USB use `adb reverse` (see docs);
// for LAN access add local HTTPS and a token before changing `host`.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
});
