import { expect, test } from "@playwright/test";
import { chooserUrl, expectStep, needsFacility, otherLanguage, pickValue, rateAll, shown } from "./helpers";

test.beforeEach(needsFacility);

test("the patient's language lasts until the thank-you page, then resets", async ({ page }) => {
  await page.goto(chooserUrl());
  const language = await otherLanguage(page);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-lang", "en");

  // Switched on the chooser…
  const title = await language.text(".hero-title");
  await language.button.click();
  await expect(html).toHaveAttribute("data-lang", language.code);
  await expect(page.locator(".hero-title")).toHaveText(title, shown);
  await page.locator("a.opt--form").first().click();

  // …the form opens in it…
  await expect(page).toHaveURL(new RegExp(`language=${language.code}`));
  await expect(html).toHaveAttribute("data-lang", language.code);
  await page.locator('[data-step="identify"] [data-action="guest"]').click();
  await pickValue(page, "clinic", "ent");
  await pickValue(page, "age_group", "18_30");
  await pickValue(page, "sex", "female");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click();
  await rateAll(page, 5);
  await page.locator('[data-step="screen-3"] [data-action="screen-next"]').click();
  await expectStep(page, "review");
  await page.locator('[data-step="review"] button[value="submit"]').click();

  // …and the thank-you page stays in it.
  await expect(page).toHaveURL(new RegExp(`/done/\\?.*language=${language.code}`));
  await expect(html).toHaveAttribute("data-lang", language.code);

  // The next patient gets the screen's own language.
  const restart = page.locator(".screen--done a.btn");
  await expect(restart).toHaveAttribute("href", chooserUrl());
  await restart.click();
  await expect(html).toHaveAttribute("data-lang", "en");
});

test("switching language keeps what was typed", async ({ page }) => {
  await page.goto(chooserUrl());
  const language = await otherLanguage(page);
  await page.locator("a.opt--form").first().click();
  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  for (const digit of "12345") await page.locator(`#keypad [data-key="${digit}"]`).click();
  const label = await language.text('[data-action="uhid-continue"]');
  await language.button.click();
  await expect(page.locator("#uhidInput")).toHaveValue("12345");
  await expect(page.locator('[data-action="uhid-continue"]')).toHaveText(label, shown);
});
