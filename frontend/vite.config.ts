import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendTarget = env.VITE_API_BASE_URL || 'http://localhost:8000';

  return {
    plugins: [
      react(),
      // Installable PWA and offline shell (Gantt R12; Frontend-Implemented 5i). The worker is
      // src/sw.ts; caching rules live there. Disabled in `npm run dev` so development stays fast.
      VitePWA({
        strategies: 'injectManifest',
        srcDir: 'src',
        filename: 'sw.ts',
        registerType: 'prompt',
        injectRegister: false,
        injectManifest: {
          // App shell only: code, styles and icons. Destination photos are excluded (PF 18.1, 19.3).
          // Manifest icons are added by the plugin itself (includeManifestIcons); only the Apple icon is listed.
          globPatterns: ['**/*.{js,css,html,woff2}', 'icons/apple-touch-icon-180.png'],
          globIgnores: ['images/**'],
          maximumFileSizeToCacheInBytes: 1024 * 1024,
        },
        manifest: {
          id: '/',
          name: 'অভিযাত্রী · Abhijatri',
          short_name: 'অভিযাত্রী',
          description: 'বাংলাদেশ ভ্রমণের বাংলা-প্রথম সঙ্গী: গন্তব্য গাইড, সতর্কতা ও রিভিউ।',
          lang: 'bn',
          dir: 'ltr',
          start_url: '/',
          scope: '/',
          display: 'standalone',
          orientation: 'portrait',
          theme_color: '#ffffff',
          background_color: '#ffffff',
          categories: ['travel'],
          icons: [
            { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
            { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
            { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        devOptions: { enabled: false },
      }),
    ],
    resolve: {
      // shadcn/ui import alias: '@/components/ui/button' -> src/components/ui/button
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  };
});
