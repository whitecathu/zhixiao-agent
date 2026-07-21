import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [vue()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "src") },
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: env.VITE_API_BASE || "http://localhost:8000",
          changeOrigin: true,
        },
        "/sse": {
          target: env.VITE_API_BASE || "http://localhost:8000",
          changeOrigin: true,
          // SSE 关键配置
          ws: false,
          configure: (proxy) => {
            proxy.on("proxyRes", (proxyRes) => {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
            });
          },
        },
      },
    },
    build: {
      target: "es2020",
      sourcemap: mode !== "prod",
      cssCodeSplit: true,
      chunkSizeWarningLimit: 1200,
      rollupOptions: {
        output: {
          manualChunks: {
            "element-plus": ["element-plus", "@element-plus/icons-vue"],
            "vue-vendor": ["vue", "vue-router", "pinia"],
            "markdown": ["marked", "highlight.js", "katex"],
          },
        },
      },
    },
  };
});