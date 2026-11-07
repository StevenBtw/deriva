/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // The studio API (deriva) runs on 8765; the dev server forwards the API paths to it.
  // A studio started on another port (deriva --port 9000) is reached with DERIVA_STUDIO_API=http://127.0.0.1:9000
  const api =
    loadEnv(mode, ".", "DERIVA_").DERIVA_STUDIO_API || "http://127.0.0.1:8765";

  return {
    plugins: [react()],
    build: {
      outDir: "../packages/deriva-studio/src/deriva/studio/static",
      emptyOutDir: true,
    },
    server: {
      // changeOrigin off: the studio's guard compares a write's Origin with its Host, so the Host must stay the dev
      // server's (the string shorthand would rewrite it to the API's address and every write would be refused)
      proxy: Object.fromEntries(
        ["/api", "/grafeo", "/widgets", "/docs", "/openapi.json"].map(
          (path) => [path, { target: api, changeOrigin: false }],
        ),
      ),
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
