import { expect, test } from "@playwright/test";
import { chooserUrl, enterUhid, expectStep, formUrl, needsFacility } from "./helpers";

test.beforeEach(needsFacility);

// The default IDLE_TIMEOUT_SECONDS is 90, with a warning in the last 15.

test("an abandoned form warns, then starts over for the next patient", async ({ page }) => {
  await page.clock.install();
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await expectStep(page, "details");

  await page.clock.fastForward(76_000);
  await expect(page.locator("#idleOverlay")).toBeVisible();
  await expect(page.locator("#idleBody")).toContainText("Starting over in");

  await page.clock.fastForward(16_000);
  await expectStep(page, "identify");
  await expect(page.locator("#uhidInput")).toHaveValue("");
});

test("a touch during the warning keeps the patient's answers", async ({ page }) => {
  await page.clock.install();
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await page.clock.fastForward(76_000);
  await expect(page.locator("#idleOverlay")).toBeVisible();
  await page.mouse.click(10, 10);
  await expect(page.locator("#idleOverlay")).toBeHidden();
  await page.clock.fastForward(30_000);
  await expectStep(page, "details");
  await expect(page.locator("#uhidInput")).toHaveValue("12345678901");
});

test("an untouched screen never reloads", async ({ page }) => {
  await page.clock.install();
  await page.goto(formUrl("opd"));
  let loads = 0;
  page.on("load", () => loads++);
  await page.clock.fastForward(300_000);
  await expect(page.locator("#idleOverlay")).toBeHidden();
  expect(loads).toBe(0);
});

test("a language switched on the chooser is undone for the next patient", async ({ page }) => {
  await page.clock.install();
  await page.goto(chooserUrl());
  const kannada = page.locator('[data-set-lang="kn"]');
  test.skip((await kannada.count()) === 0, "Kannada is not in the backend's LANGUAGES");
  await kannada.click();
  await expect(page.locator("html")).toHaveAttribute("data-lang", "kn");
  await page.clock.fastForward(92_000);
  await expect(page.locator("html")).toHaveAttribute("data-lang", "en");
});
