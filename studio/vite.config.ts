/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // The studio API (deriva) runs on 8765; the dev server forwards the API paths to it.
  // A studio started on another port (deriva --port 9000) is reached with DERIVA_STUDIO_API=http://127.0.0.1:9000
  const api = loadEnv(mode, ".", "DERIVA_").DERIVA_STUDIO_API || "http://127.0.0.1:8765";

  return {
    plugins: [react()],
    build: {
      outDir: "../packages/deriva-studio/src/deriva/studio/static",
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
      // CSS is not processed in tests, except the tokens file its drift test reads
      css: { include: [/tokens\.css/] },
      // Each test counts only its own calls (the mocks keep their implementations)
      clearMocks: true,
    },
  };
});
