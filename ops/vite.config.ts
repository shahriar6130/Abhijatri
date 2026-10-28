import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Separate app on its own port and its own Vercel project (System-Monitoring-Dashboard 2, rule R1).
export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true },
  preview: { port: 5174, strictPort: true },
});
