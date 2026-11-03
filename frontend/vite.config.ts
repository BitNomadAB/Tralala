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
    // `pnpm test:coverage` (CI): every source file counts, tested or not, and the floors are the
    // measured values, so coverage can only go up. Raise them when it does.
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/tests/**", "src/**/*.d.ts"],
      reporter: ["text-summary", "html"],
      reportsDirectory: "coverage",
      thresholds: { statements: 23.5, branches: 15.3, functions: 15, lines: 23.5 },
    },
  },
});
