import { expect, test } from "@playwright/test";

/** Runs only against a served production build (`fods serve`), where the strict
 *  CSP is actually sent. Vite dev has none, so a pass here is the one that
 *  counts for the slice definition of done.
 *
 *  A CSP violation is a console error and a `securitypolicyviolation` event.
 *  CSSOM writes and SVG presentation attributes are allowed; an inline `style`
 *  attribute in HTML is not the assertion any more. */

const CSP_PROBE = () => {
  window.__cspViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    window.__cspViolations.push({
      directive: event.violatedDirective,
      blocked: event.blockedURI,
      sample: event.sample,
    });
  });
};

async function watch(page) {
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  await page.addInitScript(CSP_PROBE);
  return consoleErrors;
}

async function cspViolations(page) {
  return page.evaluate(() => window.__cspViolations || []);
}

test("shell loads and runs the demo under the production CSP", async ({ page }) => {
  const consoleErrors = await watch(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /what should we investigate/i })).toBeVisible();
  await expect(page.getByText("Local runtime ready")).toBeVisible();

  await page.getByRole("button", { name: /run the deterministic demo/i }).click();

  const article = page.getByRole("article");
  await expect(article).toBeVisible();
  await expect(article.getByLabel("Status: Completed")).toBeVisible({ timeout: 30_000 });
  await expect(article).toContainText("events");
  await expect(article.getByRole("button", { name: /open execution trace/i })).toBeVisible();

  expect(await cspViolations(page), JSON.stringify(await cspViolations(page))).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("theme switch goes through data-theme and keeps the CSP clean", async ({ page }) => {
  const consoleErrors = await watch(page);
  await page.goto("/");

  const toggle = page.getByRole("button", { name: /system theme/i });
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /light theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /dark theme/i }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme");

  expect(await cspViolations(page)).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

for (const width of [1280, 768]) {
  test(`no horizontal page scroll at ${width}px`, async ({ page }) => {
    const consoleErrors = await watch(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /what should we investigate/i })).toBeVisible();

    const overflow = await page.evaluate(() => ({
      root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
    }));
    expect(overflow.root).toBeLessThanOrEqual(0);
    expect(overflow.body).toBeLessThanOrEqual(0);

    if (width === 768) {
      const sidebar = await page.locator(".sidebar").boundingBox();
      expect(sidebar.width).toBeLessThanOrEqual(70);
      await expect(page.locator(".brand-text")).toBeHidden();
    }

    expect(await cspViolations(page)).toEqual([]);
    expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
  });
}
