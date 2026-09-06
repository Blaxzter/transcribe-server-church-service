import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

/**
 * Builds src/__preview.tsx into one self-contained file, so a dialog can be
 * looked at without a backend and without a dev server (the browser tooling
 * here cannot reach localhost). See scripts/preview-dialog.mjs.
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "dist-preview",
    emptyOutDir: true,
    sourcemap: false,
    // One chunk: a lazily imported renderer would be a second file the
    // inlined page could never fetch.
    rollupOptions: {
      input: path.resolve(__dirname, "preview.html"),
      output: { inlineDynamicImports: true },
    },
  },
});
