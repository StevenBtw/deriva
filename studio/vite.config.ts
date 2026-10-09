/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The studio API (deriva) runs on 8765; the dev server forwards the API paths to it.
const api = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../deriva/studio/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": api,
      "/grafeo": api,
      "/widgets": api,
      "/docs": api,
      "/openapi.json": api,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
