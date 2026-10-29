import { defineConfig } from "vite";

const backendPort = process.env.FLIGHTBENCH_BACKEND_PORT || "8000";

export default defineConfig(({ mode }) => ({
  base: mode === "pages" ? "/FlightBench/" : "/",
  plugins: mode === "pages" ? [{
    name: "pages-security-policy",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { name: "referrer", content: "no-referrer" }, injectTo: "head-prepend" },
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content:
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self' https://*.workers.dev; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; form-action 'none'" }, injectTo: "head-prepend" },
    ],
  }] : [],
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
}));
