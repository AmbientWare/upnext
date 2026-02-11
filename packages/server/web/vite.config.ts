import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [tanstackRouter({ quoteStyle: "double" }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("/node_modules/")) return;

          if (
            id.includes("/node_modules/react/") ||
            id.includes("/node_modules/react-dom/") ||
            id.includes("/node_modules/scheduler/")
          ) {
            return "vendor-react";
          }

          if (id.includes("/node_modules/@tanstack/")) {
            return "vendor-tanstack";
          }

          if (
            id.includes("/node_modules/@radix-ui/") ||
            id.includes("/node_modules/radix-ui/")
          ) {
            return "vendor-radix";
          }

          if (id.includes("/node_modules/recharts/")) {
            return "vendor-recharts";
          }

          if (
            id.includes("/node_modules/react-syntax-highlighter/") ||
            id.includes("/node_modules/highlight.js/") ||
            id.includes("/node_modules/prismjs/")
          ) {
            return "vendor-syntax";
          }

          if (id.includes("/node_modules/date-fns/")) {
            return "vendor-date";
          }

          return "vendor-misc";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api/": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      thresholds: {
        statements: 70,
        branches: 50,
        functions: 70,
        lines: 70,
      },
    },
  },
});
