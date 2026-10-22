import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const here = dirname(fileURLToPath(import.meta.url));
// Same variable the Python server reads for its port.
const PYTHON_SERVER = `http://127.0.0.1:${process.env.MYCELIUM_HTTP_PORT ?? '8765'}`;

// The browser app, served at /ui/. The output lands inside the Python package
// and is committed, so `uv sync && uv run mycelium-http` works without Node;
// CI rebuilds and fails on any diff.
export default defineConfig({
  root: here,
  plugins: [react()],
  build: {
    outDir: resolve(here, '../src/mycelium/webui'),
    emptyOutDir: true,
    // Bundles live under /ui/assets/ so the /ui static mount serves them; a
    // separate /assets mount would need its own route ahead of the catch-all
    // MCP app at "/".
    assetsDir: 'ui/assets',
    // Readable CSS in the committed build keeps its diffs reviewable.
    cssMinify: false,
    rolldownOptions: {
      input: { ui: resolve(here, 'ui/index.html') },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Vite serves the app; everything else (API, auth, MCP, the /cockpit
    // redirect) belongs to the Python server.
    proxy: {
      '^/(?!ui/|@|node_modules/).*': {
        target: PYTHON_SERVER,
        changeOrigin: false,
      },
    },
  },
});
