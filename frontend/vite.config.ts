import { defineConfig } from "vite";

const backendPort = process.env.FLIGHTBENCH_BACKEND_PORT || "8000";

export default defineConfig({
  server: {
    open: true,
    strictPort: false,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
      "/ws": {
        target: `ws://127.0.0.1:${backendPort}`,
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
