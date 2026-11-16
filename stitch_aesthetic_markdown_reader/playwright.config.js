import { defineConfig } from "@playwright/test";

/** Playwright is a development-only tool: it is not part of the per-slice gate
 *  and not installed in the Docker image. Point it at a running `fods serve`
 *  instance (the default port is 8765; set FODS_BASE_URL for another port). */
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.FODS_BASE_URL || "http://127.0.0.1:8765",
    trace: "off",
    video: "off",
    screenshot: "off",
  },
});
