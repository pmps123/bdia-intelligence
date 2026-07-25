import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // tsconfig.json sets "jsx": "preserve" (Next.js/SWC handles the actual transform at build
  // time). Vite 8's oxc transform picks that up too and leaves JSX untransformed, which then
  // fails import analysis. Override just for the test transform — doesn't affect Next's build.
  oxc: {
    jsx: { runtime: "automatic" },
  },
  test: {
    environment: "node",
  },
});
