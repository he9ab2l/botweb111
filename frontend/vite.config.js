import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'
import { VitePWA } from 'vite-plugin-pwa'

const here = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/icon.svg', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png'],
      manifest: {
        name: 'FanBot',
        short_name: 'FanBot',
        description: 'FanBot - AI Assistant by FanFan',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#ffffff',
        theme_color: '#ffffff',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        runtimeCaching: [
          { urlPattern: ({ url }) => url.pathname.startsWith('/api'), handler: 'NetworkOnly' },
          { urlPattern: ({ url }) => url.pathname.startsWith('/event'), handler: 'NetworkOnly' },
        ],
      },
    }),
  ],
  build: {
    outDir: path.resolve(here, '../nanobot/web/static/dist'),
    emptyOutDir: true,
  },
  server: {
    port: 4444,
    hmr: { port: 4444, clientPort: 4444 },
    proxy: { '/api': 'http://127.0.0.1:4096', '/event': 'http://127.0.0.1:4096' },
  },
})
