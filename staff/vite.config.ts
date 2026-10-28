import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Separate app on its own port and its own Vercel project (Moderation spec 3.2; staff screens are a separate build, never part of the public app).
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, strictPort: true },
  preview: { port: 5175, strictPort: true },
});
