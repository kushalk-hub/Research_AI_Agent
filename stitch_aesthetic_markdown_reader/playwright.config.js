import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Playwright is a development-only tool: it is not part of the per-slice gate
 *  and not installed in the Docker image.
 *
 *  It starts its own `fods serve` with RLA_DATA_DIR pointing at a throwaway
 *  directory, so an e2e run never writes into the real `data/fods/` corpus.
 *  `globalTeardown` deletes that directory. */
const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");
const python = resolve(repo, ".venv", "Scripts", "python.exe");
// The webapp resolves output files (data/fods/briefs) against the *parent* of
// data_dir, so the data dir sits one level down inside the throwaway root.
const root = resolve(here, ".e2e-data");
const dataDir = resolve(root, "data");
const port = Number(process.env.FODS_E2E_PORT || 8901);

process.env.FODS_E2E_ROOT = root;

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  reporter: [["list"]],
  globalTeardown: "./e2e/global-teardown.js",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: {
    command: `"${python}" -m fods.cli serve --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    cwd: repo,
    env: {
      ...process.env,
      RLA_DATA_DIR: dataDir,
      PYTHONPATH: resolve(repo, "src"),
    },
  },
});
