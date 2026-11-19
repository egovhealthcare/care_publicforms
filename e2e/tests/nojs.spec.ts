import { expect, test } from "@playwright/test";
import { formUrl, needsFacility } from "./helpers";

test.beforeEach(needsFacility);

test("without JavaScript the form is one long page that submits", async ({ page }) => {
  await page.goto(formUrl("opd"));
  for (const step of ["uhid", "details", "questions", "comments"]) {
    await expect(page.locator(`[data-step="${step}"]`)).toBeVisible();
  }
  for (const step of ["identify", "scan", "review"]) {
    await expect(page.locator(`[data-step="${step}"]`)).toBeHidden();
  }
  const cards = page.locator("[data-card]");
  await expect(cards).toHaveCount(10);
  for (let i = 0; i < 10; i++) await expect(cards.nth(i)).toBeVisible();

  await page.locator("#uhidInput").fill("12345678901");
  await page.locator('label.chip:has(input[name="clinic"][value="ent"])').click();
  for (let i = 0; i < 10; i++) await cards.nth(i).locator('label.rate-option:has(input[value="4"])').click();
  await page.locator(".submit-row button[type=submit]").click();
  await expect(page).toHaveURL(/\/done\/\?.*ref=OPD-\d{8}-\d{4}/);
  await expect(page.locator(".token")).toHaveText(/^OPD-/);
});

test("without JavaScript missing answers come back marked", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await page.locator("#uhidInput").fill("12345678901");
  await page.locator(".submit-row button[type=submit]").click();
  await expect(page.getByRole("alert").filter({ hasText: "Please answer the questions marked below." })).toBeVisible();
  await expect(page.locator('[data-question-key="clinic"] [data-error]')).toBeVisible();
  await expect(page.locator("#uhidInput")).toHaveValue("12345678901");
});
