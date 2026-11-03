import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiProxyTarget = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // One 672 kB chunk meant every deploy invalidated the whole bundle for a browser cache that
        // had already downloaded React. Splitting the frameworks out keeps their hashes stable
        // across application changes and removes the chunk-size warning.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          if (id.includes("react-router")) return "router";
          if (id.includes("@tanstack")) return "query";
          if (id.includes("lucide-react")) return "icons";
          return "vendor";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
      "/docs": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
      "/openapi.json": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
      "/llms.txt": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
      "/mcp": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
