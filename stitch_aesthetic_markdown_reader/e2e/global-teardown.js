import { rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Remove the throwaway root the e2e server wrote to (logs, briefs, topic
 *  snapshots). The real `data/fods/` corpus is never touched: configuring
 *  RLA_DATA_DIR in playwright.config.js is what keeps them separate. */
export default function globalTeardown() {
  const here = dirname(fileURLToPath(import.meta.url));
  const root = process.env.FODS_E2E_ROOT || resolve(here, "..", ".e2e-data");
  rmSync(root, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
}
