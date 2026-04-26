/**
 * vite.config.js — Vite build tool configuration
 *
 * Configures:
 *   1. React plugin — enables JSX transform and Fast Refresh in development
 *   2. Dev server proxy — forwards /api requests to the API Gateway URL
 *      so the frontend can call the backend without CORS issues during development
 *
 * The proxy is only active during "npm run dev" (development mode).
 * In production, the frontend calls VITE_API_URL directly.
 *
 * Environment variables (set in .env file):
 *   VITE_API_URL              — API Gateway endpoint URL
 *   VITE_COGNITO_USER_POOL_ID — Cognito User Pool ID
 *   VITE_COGNITO_CLIENT_ID    — Cognito App Client ID
 *
 * All VITE_* variables are embedded into the bundle at build time.
 * They are NOT secret — do not put API keys or passwords in VITE_* variables.
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [
    // @vitejs/plugin-react enables:
    //   - JSX transform (no need to import React in every file)
    //   - React Fast Refresh (hot module replacement for React components)
    react(),
  ],

  // Polyfill Node.js 'global' for amazon-cognito-identity-js.
  // The library uses 'global' which exists in Node but not in browsers.
  // Mapping it to 'globalThis' fixes the "global is not defined" error.
  define: {
    global: 'globalThis',
  },

  server: {
    proxy: {
      // Proxy /api/* requests to the API Gateway URL during development.
      // This avoids CORS issues when the frontend (localhost:5173) calls
      // the backend (different domain).
      //
      // Example: GET /api/jobs → GET https://abc123.execute-api.../prod/jobs
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:3000',
        changeOrigin: true,  // Changes the Host header to match the target
        // Remove the /api prefix before forwarding to the backend
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
