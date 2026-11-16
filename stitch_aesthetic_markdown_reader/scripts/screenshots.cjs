const { chromium } = require("@playwright/test");
const { mkdirSync } = require("node:fs");

/** Screenshots for the owner review. Points at a served production build. For
 *  local work that server must use a throwaway RLA_DATA_DIR, so this script
 *  never adds runs to the real corpus. */
const BASE = process.env.FODS_BASE_URL || "http://127.0.0.1:8901";
const OUT = "../docs/audit/screenshots";

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const problems = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));
  await page.addInitScript(() => {
    window.__cspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.__cspViolations.push(event.violatedDirective);
    });
  });

  const settle = () => page.waitForTimeout(300);
  const footer = async (name) => {
    await settle();
    await page.locator(".sidebar").screenshot({ path: `${OUT}/${name}.png` });
  };
  const overflow = () =>
    page.evaluate(() => ({
      root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
    }));

  await page.goto(BASE);
  await page.getByRole("heading", { name: /what should we investigate/i }).waitFor();
  await page.getByText("Local runtime ready").waitFor();
  await settle();

  await footer("slice1.1-footer-system");
  await page.screenshot({ path: `${OUT}/slice1.1-empty-1280.png` });
  const wideOverflow = await overflow();

  await page.getByRole("button", { name: /system theme/i }).click();
  await footer("slice1.1-footer-light");
  await page.screenshot({ path: `${OUT}/slice1.1-empty-1280-light.png` });

  await page.getByRole("button", { name: /light theme/i }).click();
  await footer("slice1.1-footer-dark");
  await page.screenshot({ path: `${OUT}/slice1.1-empty-1280-dark.png` });

  await page.getByRole("button", { name: /dark theme/i }).click();
  await page.setViewportSize({ width: 768, height: 900 });
  await settle();
  const narrowOverflow = await overflow();
  await page.screenshot({ path: `${OUT}/slice1.1-empty-768-collapsed.png` });
  const sidebar = await page.locator(".sidebar").boundingBox();

  console.log(
    JSON.stringify(
      {
        base: BASE,
        consoleErrors: problems,
        cspViolations: await page.evaluate(() => window.__cspViolations || []),
        overflow1280: wideOverflow,
        overflow768: narrowOverflow,
        sidebar768: sidebar && Math.round(sidebar.width),
      },
      null,
      2,
    ),
  );
  await browser.close();
})();
