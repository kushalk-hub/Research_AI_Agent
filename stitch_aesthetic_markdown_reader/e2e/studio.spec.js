import { expect, test } from "@playwright/test";

/** Runs only against a served production build (`fods serve`), where the strict
 *  CSP is actually sent. Vite dev has no CSP, so a pass here is the one that
 *  counts for the slice definition of done. */
test("shell loads under the production CSP and never takes an inline style", async ({ page }) => {
  const problems = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));

  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: /ask a question the record can prove/i }),
  ).toBeVisible();
  await expect(page.getByText("Local runtime ready")).toBeVisible();

  expect(await page.locator("[style]").count()).toBe(0);

  await page.getByRole("button", { name: /run the deterministic demo/i }).click();

  const article = page.getByRole("article");
  await expect(article).toBeVisible();
  await expect(article.getByLabel("Status: Completed")).toBeVisible({ timeout: 30_000 });
  await expect(article).toContainText("events");
  await expect(article.getByRole("button", { name: /open execution trace/i })).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("theme switch is applied through a data attribute", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /system theme/i });
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /light theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.locator("[style]").count()).toBe(0);
});
