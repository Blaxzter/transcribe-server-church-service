import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    // Dev server talks to the API container; same paths as production so the
    // upload client never needs to know which mode it is in.
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
      "/files": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
