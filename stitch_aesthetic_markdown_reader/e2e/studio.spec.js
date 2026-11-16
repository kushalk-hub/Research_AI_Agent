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

test("the + menu states the live blocker, shows config facts and keeps the layout", async ({
  page,
}) => {
  const consoleErrors = await watch(page);
  await page.goto("/");

  // With no GEMINI_API_KEY in the isolated runtime this is the reachable mode.
  await expect(page.getByText(/deterministic demo · fods scheduler/i)).toBeVisible();

  await page.getByRole("button", { name: /run settings/i }).click();
  const dialog = page.getByRole("dialog", { name: /run settings/i });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/live runs need/i)).toBeVisible();
  await expect(dialog.getByText("ollama/qwen3:4b").first()).toBeVisible();
  await expect(dialog.getByText("Sources")).toBeVisible();
  await expect(dialog.getByText("Daily cap")).toBeVisible();

  // Advanced is collapsed by default, then shows the runtime defaults.
  await expect(dialog.getByLabel(/papers to keep/i)).toHaveCount(0);
  await dialog.getByRole("button", { name: /advanced/i }).click();
  await expect(dialog.getByLabel(/papers to keep/i)).toHaveValue("20");
  await expect(dialog.getByLabel(/model requests for this run/i)).toHaveValue("15");

  const overflow = await page.evaluate(() => ({
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.root).toBeLessThanOrEqual(0);
  expect(overflow.body).toBeLessThanOrEqual(0);

  await page.setViewportSize({ width: 768, height: 900 });
  const narrow = await page.evaluate(() => ({
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(narrow.root).toBeLessThanOrEqual(0);
  expect(narrow.body).toBeLessThanOrEqual(0);

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  expect(await cspViolations(page)).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("the completed turn collapses to the recorded worked-for summary", async ({ page }) => {
  const consoleErrors = await watch(page);
  await page.goto("/");
  await page.getByRole("button", { name: /run the deterministic demo/i }).click();

  const article = page.getByRole("article");
  await expect(article.getByLabel("Status: Completed")).toBeVisible({ timeout: 30_000 });
  const workedFor = article.getByRole("button", {
    name: /worked for .+ · \d+ steps? — open execution trace/i,
  });
  await expect(workedFor).toBeVisible();
  await expect(article.locator(".working")).toHaveCount(0);

  await workedFor.click();
  await expect(
    page.getByRole("heading", { level: 1, name: /execution trace/i }),
  ).toBeVisible();

  expect(await cspViolations(page)).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("Stop asks the runtime to cancel a live demo and reports what was recorded", async ({
  page,
}) => {
  const consoleErrors = await watch(page);
  await page.goto("/");
  await page.getByRole("button", { name: /run the deterministic demo/i }).click();

  const stop = page.getByRole("button", { name: /^stop$/i });
  await expect(stop).toBeVisible();
  await stop.click();

  const article = page.getByRole("article");
  await expect(article.getByLabel("Status: Stopped")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /^stop$/i })).toHaveCount(0);
  await expect(article.getByRole("button", { name: /worked for/i })).toBeVisible();

  expect(await cspViolations(page)).toEqual([]);
  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("citation chips resolve to evidence and highlight in both directions", async ({ page }) => {
  const consoleErrors = await watch(page);
  await page.goto("/");
  await page.getByRole("button", { name: /run the deterministic demo/i }).click();

  const article = page.getByRole("article");
  await expect(article.getByLabel("Status: Completed")).toBeVisible({ timeout: 30_000 });
  const answer = article.getByRole("region", { name: "Answer" });
  await expect(answer).toBeVisible();

  const p2Chip = answer.locator('.cite-row .cite-chip[data-citation="P2"]');
  await expect(p2Chip).toHaveAttribute("aria-pressed", "false");
  await p2Chip.click();

  const p2Card = answer.locator('.evidence-item[data-citation="P2"]');
  await expect(p2Chip).toHaveAttribute("aria-pressed", "true");
  await expect(p2Card).toHaveAttribute("data-active", "true");
  await expect(p2Card).toHaveAttribute("aria-pressed", "true");

  const p3Card = answer.locator('.evidence-item[data-citation="P3"]');
  await p3Card.hover();
  await expect(answer.locator('.cite-chip[data-citation="P3"]').first()).toHaveAttribute(
    "data-active",
    "true",
  );
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
