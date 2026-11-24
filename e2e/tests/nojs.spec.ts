import { expect, test, type Page } from "@playwright/test";
import {
  activeCard,
  activeStep,
  confirmCard,
  counter,
  counterText,
  expectStep,
  formUrl,
  headerNav,
  isoDate,
  needsFacility,
  otherLanguage,
  pickDetail,
  requiredError,
  reviewRow,
  shown,
  UHID,
} from "./helpers";

test.beforeEach(needsFacility);

// Reduced motion, so each step appears without sliding in: before a click,
// Playwright waits for a moving element to settle, and with JavaScript off
// that wait stalls for half a minute. (The project's reducedMotion option
// doesn't reach a page without JavaScript; emulateMedia does.)
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

// Without JavaScript every step button posts the page and the server shows
// the next step: the same steps as with JavaScript, one page each.

async function answerCard(page: Page, value: number) {
  const card = activeCard(page);
  const key = await card.getAttribute("data-question-key");
  await card.locator(`label.rate-option:has(input[value="${value}"])`).click();
  await card.locator('[data-nav="next"]').click(); // "Next", or "Review answers" when changing one from it
  await expect(page.locator(`[data-card][data-question-key="${key}"]`)).toBeHidden();
}

/** A screen's main button ("Start the questions", "Next", "Review answers"). */
function mainButton(page: Page) {
  return activeStep(page).locator('[data-action="screen-next"]');
}

/** Without JavaScript: a typed UHID, the ENT clinic, then the first rating card. */
async function toRatings(page: Page): Promise<void> {
  await page.goto(formUrl("opd"));
  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  await page.locator("#uhidInput").fill(UHID);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await pickDetail(page, "clinic", "ENT");
  await page.getByRole("button", { name: "Start the questions" }).click();
  await expectStep(page, "questions");
}

/** Without JavaScript: on to the open questions, every rating 4. */
async function toOpenQuestions(page: Page): Promise<void> {
  await toRatings(page);
  for (let i = 0; i < 10; i++) await answerCard(page, 4);
  await expectStep(page, "screen-3");
}

async function toReview(page: Page): Promise<void> {
  await toOpenQuestions(page);
  await mainButton(page).click();
  await expectStep(page, "review");
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
  // The page now holds an answer: it starts over 3 minutes after it loaded
  // (it can't see touches without JavaScript). The countdown in the header
  // shows only for the last minute.
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveAttribute("content", /^180;url=/);
  await expect(page.locator(".tick-timer")).toHaveCount(1);
  await expect(page.locator(".tick-timer")).toBeHidden();
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
  await expect(page.locator("#scrollDown")).toBeHidden(); // the down arrow needs JavaScript
  await activeStep(page).locator("label.yn", { hasText: "Yes" }).click();
  await activeStep(page).getByLabel("Why? (optional)").fill("Friendly staff");
  await page.getByRole("button", { name: "Review answers" }).click();

  await expectStep(page, "review");
  await expect(page.locator("#reviewRows .row")).toHaveCount(15);
  await expect(reviewRow(page, "Clinic visited")).toContainText("ENT");
  await expect(reviewRow(page, "Would return to this hospital")).toContainText("Friendly staff");

  // Edit from the review, then straight back to it: no Back on the way, and
  // the button says where it goes.
  await reviewRow(page, "Registration wait").click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "registration_wait");
  await expect(activeCard(page).getByRole("button", { name: "Back", exact: true })).toBeHidden();
  await expect(activeCard(page).locator('[data-nav="next"]')).toHaveText("Review answers", shown);
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
  await activeCard(page).getByRole("button", { name: "Back", exact: true }).click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "information_signage");
  await expect(activeCard(page).locator('input[value="5"]')).toBeChecked();
  await activeCard(page).getByRole("button", { name: "Back", exact: true }).click();
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

test("without JavaScript a first-screen answer changed from the review comes straight back", async ({ page }) => {
  await toReview(page);
  await reviewRow(page, "Clinic visited").click();
  await expectStep(page, "screen-1");
  await expect(activeStep(page).getByRole("button", { name: "Back", exact: true })).toBeHidden();
  await expect(mainButton(page)).toHaveText("Review answers", shown); // not "Start the questions"
  await pickDetail(page, "clinic", "Dental");
  await mainButton(page).click();
  await expectStep(page, "review");
  await expect(reviewRow(page, "Clinic visited")).toContainText("Dental");

  // The review's own Back still steps back through the questions, with their Back.
  await activeStep(page).getByRole("button", { name: "Back", exact: true }).click();
  await expectStep(page, "screen-3");
  await expect(activeStep(page).getByRole("button", { name: "Back", exact: true })).toBeVisible();
});

test("without JavaScript a new UHID or a switch to guest from the review comes back to it", async ({ page }) => {
  await toReview(page);
  await page.locator("#idStrip").click();
  await expectStep(page, "uhid");
  await page.locator("#uhidInput").fill("98765432100");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expectStep(page, "review");
  await expect(page.locator("#idStripValue")).toHaveText("987 6543 2100");

  // As a guest: first the guest-only details, then the review again.
  await page.locator("#idStrip").click();
  await page.locator('[data-step="uhid"] [data-action="guest"]').click();
  await expectStep(page, "screen-1");
  await expect(page.locator("#idStrip")).toBeHidden();
  await expect(page.locator('input[name="clinic"][value="ent"]')).toBeChecked();
  await expect(mainButton(page)).toHaveText("Review answers", shown);
  await mainButton(page).click();
  await expect(requiredError(page, "age_group")).toBeVisible();
  await pickDetail(page, "age_group", "Over 60");
  await pickDetail(page, "sex", "Male");
  await mainButton(page).click();
  await expectStep(page, "review");
  await expect(reviewRow(page, "Age group")).toContainText("Over 60");
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(10);
});

test("without JavaScript the server turns away characters that could carry code", async ({ page }) => {
  await toOpenQuestions(page);
  // Nothing strips them as they're typed: the server refuses them, keeping the text to correct.
  const box = activeStep(page).getByLabel("What would you most like to see improved?");
  await box.fill("Wait <10 mins>");
  await mainButton(page).click();
  await expectStep(page, "screen-3");
  await expect(activeStep(page).locator('[data-question-key="improvement"] [data-error-characters]')).toBeVisible();
  await expect(box).toHaveValue("Wait <10 mins>");
  await box.fill("Wait 10 mins");
  await mainButton(page).click();
  await expectStep(page, "review");
  await expect(reviewRow(page, "What would you most like to see improved?")).toContainText("Wait 10 mins");
});

test("without JavaScript a date in the future is turned away", async ({ page }) => {
  await page.goto(formUrl("ipd"));
  await page.getByRole("button", { name: /Continue as guest/ }).click();
  await expectStep(page, "screen-1");
  await pickDetail(page, "ward", "General Surgery");
  const date = activeStep(page).locator('input[type="date"]');
  await date.fill(isoDate(3));
  await pickDetail(page, "age_group", "Over 60");
  await pickDetail(page, "sex", "Male");
  await mainButton(page).click();
  await expectStep(page, "screen-1");
  await expect(activeStep(page).locator("[data-error-date]")).toBeVisible();
  await date.fill(isoDate(-1));
  await mainButton(page).click();
  await expectStep(page, "questions");
});

test("without JavaScript Home and Reset ask first too", async ({ page }) => {
  await toRatings(page);
  await answerCard(page, 5);
  await answerCard(page, 4);
  const nav = headerNav(page);
  await expect(nav.getByRole("link")).toHaveCount(0); // buttons that post the page, not links

  // Reset: "No, keep my answers" (the default) leaves everything as it was.
  await nav.getByRole("button", { name: "Reset" }).click();
  const reset = confirmCard(page, "reset");
  await expect(reset).toBeVisible();
  await expect(reset.getByRole("button", { name: "No, keep my answers" })).toBeFocused();
  await reset.getByRole("button", { name: "No, keep my answers" }).click();
  await expect(reset).toBeHidden();
  await expect(counter(page)).toHaveText(counterText(3, 10), shown);
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(2);

  // "Yes, clear them": the ratings go; the UHID and the details stay, as with JavaScript.
  await nav.getByRole("button", { name: "Reset" }).click();
  await reset.getByRole("button", { name: "Yes, clear them" }).click();
  await expect(counter(page)).toHaveText(counterText(1, 10), shown);
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(0);
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
  await expect(page.locator('input[name="clinic"][value="ent"]')).toBeChecked();

  // Home: the same question, then a fresh start.
  await nav.getByRole("button", { name: "Home" }).click();
  await expect(confirmCard(page, "home")).toBeVisible();
  await confirmCard(page, "home").getByRole("link", { name: "Yes, go to home" }).click();
  await expectStep(page, "identify");
  await expect(page.locator("#uhidInput")).toHaveValue("");
  await expect(page.locator("#feedback input:checked")).toHaveCount(0);
});

test("without JavaScript the countdown shows only for the last minute, after the first page", async ({ page }) => {
  // The first page looks like the home screen: it starts over, but shows no countdown.
  await page.goto(formUrl("opd", "lang=en&from=start")); // holds the patient's choice of form
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveAttribute("content", /^180;url=/);
  const timer = page.locator(".tick-timer");
  await expect(timer).toHaveCount(0);

  await page.getByRole("button", { name: /Continue as guest/ }).click();
  await expectStep(page, "screen-1");
  await expect(timer).toHaveCount(1);
  await expect(timer).toBeHidden(); // 3 minutes left: hidden, taking no room in the header
  expect((await timer.boundingBox())?.width).toBe(0);
  // Run the page's CSS clock 100 times faster: 2 minutes pass in about a second.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Animation.enable");
  await cdp.send("Animation.setPlaybackRate", { playbackRate: 100 });
  await expect(timer).toBeVisible();
});

test("without JavaScript the thank-you page returns by itself, and Back doesn't bring it back", async ({ page }) => {
  test.slow(); // waits for the real 20-second return
  await toReview(page);
  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/done\/\?.*ref=OPD-/);
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveAttribute("content", /^20;url=/);
  await expect(page.locator(".tick-timer")).toHaveCount(0); // its own return is shorter than the idle one
  await expect(page).toHaveURL(formUrl("opd"), { timeout: 30_000 });
  await expectStep(page, "identify");

  // Chromium keeps a timed refresh in the history; the server sends the old page to the start.
  await page.goBack();
  await expect(page).not.toHaveURL(/\/done\//);
  await expect(page.locator(".token")).toHaveCount(0);
});
