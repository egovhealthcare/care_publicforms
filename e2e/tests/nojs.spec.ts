import { expect, test, type Page } from "@playwright/test";
import {
  activeCard,
  activeStep,
  counter,
  counterText,
  expectStep,
  formUrl,
  needsFacility,
  otherLanguage,
  pickDetail,
  reviewRow,
  shown,
} from "./helpers";

test.beforeEach(needsFacility);

// Without JavaScript every step button posts the page and the server shows
// the next step: the same steps as with JavaScript, one page each.

async function answerCard(page: Page, value: number) {
  const card = activeCard(page);
  const key = await card.getAttribute("data-question-key");
  await card.locator(`label.rate-option:has(input[value="${value}"])`).click();
  await card.getByRole("button", { name: "Next" }).click();
  await expect(page.locator(`[data-card][data-question-key="${key}"]`)).toBeHidden();
}

test("without JavaScript the kiosk still goes step by step", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await expectStep(page, "identify");
  await expect(page.locator(".tick-timer")).toHaveCount(0); // an untouched screen never starts over
  await expect(page.getByRole("button", { name: /Continue as guest/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Scan the QR/ })).toBeHidden(); // needs JavaScript

  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  await expectStep(page, "uhid");
  await expect(page.locator("#keypad")).toBeHidden(); // a plain field instead
  await page.locator("#uhidInput").fill("12345");
  await page.locator("#uhidInput").press("Enter"); // Enter continues, like the button
  await expectStep(page, "uhid");
  await expect(page.locator("#uhidErr")).toBeVisible();
  // The page now holds an answer: it starts over 3 minutes after it loaded,
  // counting down in the header (it can't see touches without JavaScript).
  await expect(page.locator(".tick-timer")).toBeVisible();
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveAttribute("content", /^180;url=/);
  await page.locator("#uhidInput").fill("12345678901");
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  await expectStep(page, "screen-1");
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
  await expect(page.locator('[data-question-key="age_group"]')).toBeHidden();
  await page.getByRole("button", { name: "Start the questions" }).click();
  await expect(page.locator('[data-question-key="clinic"] [data-error]')).toBeVisible();
  await pickDetail(page, "clinic", "ENT");
  await page.getByRole("button", { name: "Start the questions" }).click();

  await expectStep(page, "questions");
  await expect(counter(page)).toHaveText(counterText(1, 10), shown);
  await expect(page.locator("#hdrNav")).toBeVisible();
  // Next needs an answer.
  await activeCard(page).getByRole("button", { name: "Next" }).click();
  await expect(activeCard(page).locator("[data-error]")).toBeVisible();
  for (let i = 0; i < 10; i++) await answerCard(page, 4);

  await expectStep(page, "screen-3");
  await activeStep(page).locator("label.yn", { hasText: "Yes" }).click();
  await activeStep(page).getByLabel("Why? (optional)").fill("Friendly staff");
  await page.getByRole("button", { name: "Review answers" }).click();

  await expectStep(page, "review");
  await expect(page.locator("#reviewRows .row")).toHaveCount(15);
  await expect(reviewRow(page, "Clinic visited")).toContainText("ENT");
  await expect(reviewRow(page, "Would return to this hospital")).toContainText("Friendly staff");

  // Edit from the review, then straight back to it.
  await reviewRow(page, "Registration wait").click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "registration_wait");
  await answerCard(page, 2);
  await expectStep(page, "review");
  await expect(reviewRow(page, "Registration wait")).toContainText("10-30 mins");

  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/done\/\?.*ref=OPD-\d{8}-\d{4}/);
  await expect(page.locator(".token")).toHaveText(/^OPD-/);
});

test("without JavaScript a guest answers the guest details, and Back works", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await page.getByRole("button", { name: /Continue as guest/ }).click();
  await expectStep(page, "screen-1");
  for (const key of ["clinic", "age_group", "sex"]) {
    await expect(page.locator(`[data-question-key="${key}"]`)).toBeVisible();
  }
  await pickDetail(page, "clinic", "Dental");
  await pickDetail(page, "age_group", "31-45");
  await pickDetail(page, "sex", "Female");
  await page.getByRole("button", { name: "Start the questions" }).click();
  await answerCard(page, 5);
  await activeCard(page).getByRole("button", { name: "Back" }).click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "information_signage");
  await expect(activeCard(page).locator('input[value="5"]')).toBeChecked();
  await activeCard(page).getByRole("button", { name: "Back" }).click();
  await expectStep(page, "screen-1");
  await expect(page.locator('input[name="sex"][value="female"]')).toBeChecked();
});

test("without JavaScript switching language keeps the answers", async ({ page }) => {
  await page.goto(formUrl("opd"));
  const language = await otherLanguage(page);
  await page.getByRole("button", { name: /Continue as guest/ }).click();
  await pickDetail(page, "clinic", "ENT");
  await language.button.click();
  await expect(page.locator("html")).toHaveAttribute("data-lang", language.code);
  await expectStep(page, "screen-1");
  await expect(page.locator('input[name="clinic"][value="ent"]')).toBeChecked();
});
