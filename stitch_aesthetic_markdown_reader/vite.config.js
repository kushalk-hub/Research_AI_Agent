import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(fileURLToPath(import.meta.url));
const apiPort = process.env.FODS_API_PORT || "8765";

export default defineConfig({
  root: projectRoot,
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": `http://127.0.0.1:${apiPort}` },
  },
  build: {
    outDir: resolve(projectRoot, "../src/fods/web/dist"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [resolve(projectRoot, "src/test/setup.js")],
    include: ["src/**/*.test.{js,jsx}"],
    restoreMocks: true,
  },
});
