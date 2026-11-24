import { expect, test } from "@playwright/test";
import {
  activeCard,
  activeStep,
  chooserUrl,
  confirmCard,
  continueAsGuest,
  counter,
  counterText,
  enterUhid,
  expectStep,
  facilityId,
  formUrl,
  headerNav,
  isoDate,
  needsFacility,
  opdToOpenQuestions,
  opdToReview,
  pickDetail,
  rate,
  rateAll,
  requiredError,
  reviewRow,
  shown,
} from "./helpers";

test.beforeEach(needsFacility);

// Edge cases with JavaScript on: the less common paths through a form.

async function next(page: import("@playwright/test").Page, step: string): Promise<void> {
  await page.locator(`[data-step="${step}"] [data-action="screen-next"]`).click();
}

test("an inpatient guest: ward, admission date, 20 ratings with No comments, blanks left blank", async ({ page }) => {
  await page.goto(formUrl("ipd"));
  await continueAsGuest(page);
  await expectStep(page, "screen-1");
  await pickDetail(page, "ward", "General Surgery");
  await activeStep(page).locator('input[type="date"]').fill(isoDate(-2));
  await pickDetail(page, "age_group", "Over 60");
  await pickDetail(page, "sex", "Male");
  await next(page, "screen-1");

  await expect(counter(page)).toHaveText(counterText(1, 20), shown);
  await rate(page, 0); // No comments
  for (let i = 1; i < 20; i++) await rate(page, 5);

  // Every open question is optional: straight on to the review.
  await expectStep(page, "screen-3");
  await next(page, "screen-3");
  await expectStep(page, "review");
  await expect(page.locator("#reviewRows .row")).toHaveCount(4 + 20 + 4);
  await expect(reviewRow(page, "Information at admission")).toContainText("No comments");
  await expect(reviewRow(page, "Any other suggestions?")).toContainText("Not answered");

  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/type\/ipd\/done\/\?.*ref=IPD-\d{8}-\d{4}/);
  // A screen pinned to the inpatient form returns to it.
  await expect(page.getByRole("link", { name: /another/i })).toHaveAttribute("href", formUrl("ipd"));
});

test("tapping Submit twice sends the answers once", async ({ page }) => {
  await opdToReview(page);
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") posts.push(request.url());
  });
  await page.getByRole("button", { name: "Submit feedback" }).dblclick();
  await expect(page).toHaveURL(/\/done\//);
  expect(posts).toHaveLength(1);
});

test("a Why? without a Yes or No isn't kept", async ({ page }) => {
  await opdToOpenQuestions(page);
  await activeStep(page).getByPlaceholder("Why? (optional)").fill("Too far");
  await next(page, "screen-3");
  await expect(reviewRow(page, "Would return to this hospital")).toContainText("Not answered");
  await expect(reviewRow(page, "Would return to this hospital")).not.toContainText("Too far");
});

test("an answer stops at 2000 characters", async ({ page }) => {
  await opdToOpenQuestions(page);
  const box = activeStep(page).getByLabel("What would you most like to see improved?");
  await expect(box).toHaveJSProperty("maxLength", 2000);
  await box.fill("x".repeat(2100));
  expect((await box.inputValue()).length).toBeLessThanOrEqual(2000);
});

test("the server still checks what the page let through", async ({ page }) => {
  await opdToReview(page);
  // A required answer cleared behind the page's back (a broken extension, say).
  await page.locator('input[name="clinic"]:checked').evaluate((input: HTMLInputElement) => {
    input.checked = false;
  });
  await page.getByRole("button", { name: "Submit feedback" }).click();

  // Nothing saved: the page comes back at the problem, every other answer kept.
  await expect(page).not.toHaveURL(/\/done\//);
  await expect(page.locator(".banner")).toHaveText("Please answer the questions marked below.", shown);
  await expectStep(page, "screen-1");
  await expect(requiredError(page, "clinic")).toBeVisible();
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(10);
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
});

test("a TV remote: arrows change a rating without moving on, OK moves on", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await pickDetail(page, "clinic", "ENT");
  await next(page, "screen-1");
  const card = activeCard(page);
  const key = await card.getAttribute("data-question-key");
  await card.locator('input[value="5"]').focus();
  await page.keyboard.press("ArrowDown");
  await expect(card.locator('input[value="4"]')).toBeChecked();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", key ?? ""); // not rushed on
  await page.keyboard.press("Enter");
  await expect(activeCard(page)).not.toHaveAttribute("data-question-key", key ?? "");
});

test("Back from the first step returns to the chooser", async ({ page }) => {
  await page.goto(chooserUrl());
  await page.getByRole("link", { name: /OPD feedback/ }).click();
  await expectStep(page, "identify");
  await activeStep(page).getByRole("link", { name: "Back" }).click();
  await expect(page).toHaveURL(chooserUrl());
});

test("wrong addresses: an unknown facility, form or reference", async ({ page }) => {
  const unknown = await page.goto("/facility/00000000-0000-0000-0000-000000000000/public_forms/");
  expect(unknown?.status()).toBe(404);
  await expect(page.locator("h1")).toHaveText("This facility wasn't found.");

  await page.goto(formUrl("no-such-form")); // back to the chooser
  await expect(page).toHaveURL(chooserUrl());

  await page.goto(`/facility/${facilityId}/public_forms/type/opd/done/?lang=en&ref=OPD-20000101-0000`);
  await expect(page).toHaveURL(formUrl("opd")); // no thank-you page for it
});

test("the idle reset still clears a screen left on a Home or Reset question", async ({ page }) => {
  await page.clock.install();
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await pickDetail(page, "clinic", "ENT");
  await next(page, "screen-1");
  await rate(page, 5);
  await headerNav(page).getByRole("link", { name: "Home" }).click();
  await expect(confirmCard(page, "home")).toBeVisible();

  await page.clock.fastForward(92_000); // the patient walked away
  await expectStep(page, "identify");
  await expect(confirmCard(page, "home")).toBeHidden();
  await expect(page.locator("#uhidInput")).toHaveValue("");
});

test("an answer on the first screen, changed from the review", async ({ page }) => {
  await opdToReview(page);
  await reviewRow(page, "Clinic visited").click();
  await expectStep(page, "screen-1");
  await expect(activeStep(page).getByRole("button", { name: "Back" })).toBeHidden();
  await expect(activeStep(page).locator('[data-action="screen-next"]')).toHaveText("Review answers", shown);
  await pickDetail(page, "clinic", "Dental");
  await next(page, "screen-1");
  await expectStep(page, "review");
  await expect(reviewRow(page, "Clinic visited")).toContainText("Dental");
});

test("the thank-you page returns by itself and leaves no way Back to it", async ({ page }) => {
  test.slow(); // waits for the real 20-second return
  await opdToReview(page);
  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/done\//);
  await expect(page).toHaveURL(formUrl("opd"), { timeout: 30_000 });
  await expectStep(page, "identify");
  await page.goBack();
  await expect(page).not.toHaveURL(/\/done\//);
});

test("a screen taller than the window shows a down arrow to its bottom", async ({ page }) => {
  const arrow = page.locator("#scrollDown");
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await expectStep(page, "screen-1");
  await expect(arrow).toBeHidden(); // the screen fits the window

  // A small window: "In your own words" scrolls.
  await page.setViewportSize({ width: 420, height: 600 });
  await pickDetail(page, "clinic", "ENT");
  await next(page, "screen-1");
  await rateAll(page);
  await expectStep(page, "screen-3");
  await expect(arrow).toBeVisible();
  await arrow.click();
  await expect
    .poll(() => page.evaluate(() => Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 1))
    .toBe(true);
  await expect(arrow).toBeHidden(); // nothing more below
  await expect(activeStep(page).locator('[data-action="screen-next"]')).toBeInViewport();

  // Back at the top it shows again, and steps aside while the patient types.
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(arrow).toBeVisible();
  await activeStep(page).locator('textarea[name="improvement"]').focus();
  await expect(arrow).toBeHidden();
});

test("a text box starts small and grows with what is typed, then scrolls", async ({ page }) => {
  await opdToOpenQuestions(page);
  const box = activeStep(page).locator('textarea[name="improvement"]');
  await expect(box).toHaveAttribute("rows", "2");
  const height = async () => (await box.boundingBox())!.height;
  const lines = (n: number) => Array.from({ length: n }, (_, i) => `Line ${i + 1}`).join("\n");
  const empty = await height();
  await box.fill(lines(4));
  const four = await height();
  expect(four).toBeGreaterThan(empty * 1.5);
  await box.fill(lines(12));
  const most = await height();
  expect(most).toBeGreaterThan(four);
  await box.fill(lines(30)); // no taller: it scrolls instead
  expect(await height()).toBeCloseTo(most, 0);
  expect(await box.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
  await box.fill("");
  expect(await height()).toBeCloseTo(empty, 0);
});
