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
        name: 'fanfan',
        short_name: 'fanfan',
        description: 'A self-hosted AI agent with an OpenCode-style web UI',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#f7f7f6',
        theme_color: '#f7f7f6',
        icons: [
          {
            src: '/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api'),
            handler: 'NetworkOnly',
          },
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
    hmr: {
      port: 4444,
      clientPort: 4444,
    },
    proxy: {
      '/api': 'http://127.0.0.1:4096',
    },
  },
})
