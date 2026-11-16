const { chromium } = require("@playwright/test");
const { mkdirSync } = require("node:fs");

const BASE = process.env.FODS_BASE_URL || "http://127.0.0.1:8765";
const OUT = "../docs/audit/screenshots";

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));

  const settle = async () => {
    await page.waitForTimeout(300);
  };

  await page.goto(BASE);
  await page.getByRole("heading", { name: /ask a question the record can prove/i }).waitFor();
  await page.getByText("Local runtime ready").waitFor();
  await settle();
  await page.screenshot({ path: `${OUT}/slice1-empty-light.png` });

  await page.getByRole("button", { name: /system theme/i }).click();
  await page.getByRole("button", { name: /light theme/i }).click();
  await settle();
  await page.screenshot({ path: `${OUT}/slice1-empty-dark.png` });

  await page.getByRole("button", { name: /dark theme/i }).click();
  await page.getByRole("button", { name: /run the deterministic demo/i }).click();
  await page
    .getByRole("article")
    .getByLabel("Status: Completed")
    .waitFor({ timeout: 30_000 });
  await settle();
  await page.screenshot({ path: `${OUT}/slice1-demo-light.png` });

  await page.getByRole("button", { name: /system theme/i }).click();
  await page.getByRole("button", { name: /light theme/i }).click();
  await settle();
  await page.screenshot({ path: `${OUT}/slice1-demo-dark.png` });

  console.log(JSON.stringify({ base: BASE, consoleErrors: problems }, null, 2));
  await browser.close();
})();
