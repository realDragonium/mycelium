import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const here = dirname(fileURLToPath(import.meta.url));
// Same variable the Python server reads for its port.
const PYTHON_SERVER = `http://127.0.0.1:${process.env.MYCELIUM_HTTP_PORT ?? '8765'}`;

// Two separate apps, /ui/ and /cockpit/, built in one pass so the modules they
// share (documentation, names, AI settings) are compiled once. The output lands
// inside the Python package and is committed, so `uv sync && uv run
// mycelium-http` works without Node; CI rebuilds and fails on any diff.
export default defineConfig({
  root: here,
  plugins: [react()],
  build: {
    outDir: resolve(here, '../src/mycelium/webui'),
    emptyOutDir: true,
    // Every bundle, cockpit's included, lives under /ui/assets/ so the existing
    // /ui static mount serves it. A separate /assets mount would need its own
    // route ahead of the catch-all MCP app at "/".
    assetsDir: 'ui/assets',
    // The stylesheets ship as written: concatenated, not rewritten.
    cssMinify: false,
    rolldownOptions: {
      input: {
        ui: resolve(here, 'ui/index.html'),
        cockpit: resolve(here, 'cockpit/index.html'),
      },
      output: { chunkFileNames: 'ui/assets/shared-[hash].js' },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Vite serves the two apps; everything else (API, auth, MCP) belongs to
    // the Python server.
    proxy: {
      '^/(?!ui/|cockpit/|@|node_modules/).*': {
        target: PYTHON_SERVER,
        changeOrigin: false,
      },
    },
  },
});
