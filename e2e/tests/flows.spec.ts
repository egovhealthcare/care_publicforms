import { expect, test } from "@playwright/test";
import {
  activeCard,
  activeStep,
  chooserUrl,
  continueAsGuest,
  enterUhid,
  expectStep,
  formUrl,
  headerNav,
  isoDate,
  needsFacility,
  opdToReview,
  pickDetail,
  rate,
  rateAll,
  requiredError,
  reviewRow,
  shown,
} from "./helpers";

test.beforeEach(needsFacility);

test("an identified patient answers everything and gets a reference", async ({ page }) => {
  await page.goto(chooserUrl());
  await page.getByRole("link", { name: /OPD feedback/ }).click();
  await expect(page).toHaveURL(/\/public_forms\/type\/opd\/form\/\?.*from=start/);
  await expectStep(page, "identify");
  await expect(headerNav(page)).toBeHidden();

  await enterUhid(page);
  await expectStep(page, "details");
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
  // Age and sex are only asked of guests.
  await expect(activeStep(page).locator('[data-question-key="age_group"]')).toBeHidden();
  await expect(headerNav(page)).toBeHidden();

  // The clinic is required.
  await page.locator('[data-action="details-next"]').click();
  await expectStep(page, "details");
  await expect(requiredError(page, "clinic")).toBeVisible();
  await expect(requiredError(page, "clinic")).toHaveText("This question needs an answer.", shown);
  await pickDetail(page, "clinic", "ENT");
  await expect(requiredError(page, "clinic")).toBeHidden();
  await page.locator('[data-action="details-next"]').click();

  // Home and Reset from the first question on.
  await expect(activeCard(page).locator("[data-counter]")).toHaveText("Question 1 of 10", shown);
  await expect(headerNav(page)).toBeVisible();
  expect(await rateAll(page, 4)).toBe(10);

  await expectStep(page, "comments");
  await activeStep(page).locator("label.yn", { hasText: "Yes" }).click();
  await activeStep(page).getByPlaceholder("Why? (optional)").fill("Friendly staff");
  await activeStep(page).getByLabel("What would you most like to see improved?").fill("Shorter queue");
  await page.locator('[data-action="comments-next"]').click();

  await expectStep(page, "review");
  await expect(page.locator("#reviewRows .row")).toHaveCount(15);
  await expect(reviewRow(page, "Clinic visited")).toContainText("ENT");
  await expect(reviewRow(page, "Would return to this hospital")).toContainText("Yes");
  await expect(reviewRow(page, "Would return to this hospital")).toContainText("Friendly staff");
  await expect(reviewRow(page, "Any other suggestions?")).toContainText("Not answered");

  // Editing an answer from the review comes straight back to it.
  await reviewRow(page, "Registration wait").click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "registration_wait");
  await rate(page, 2);
  await expectStep(page, "review");
  await expect(reviewRow(page, "Registration wait")).toContainText("10-30 mins");

  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/public_forms\/type\/opd\/done\/\?.*ref=OPD-\d{8}-\d{4}/);
  await expect(page.locator(".token")).toHaveText(/^OPD-\d{8}-\d{4}$/);
  await expect(page.locator("h2.done-title")).toHaveText("Thank you.", shown);
  // The next patient starts at the chooser.
  await expect(page.getByRole("link", { name: /another|start/i })).toHaveAttribute(
    "href",
    chooserUrl(),
  );
});

test("a guest must answer the details", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await continueAsGuest(page);
  await expectStep(page, "details");
  const details = activeStep(page);
  for (const key of ["clinic", "age_group", "sex"]) {
    await expect(details.locator(`[data-question-key="${key}"]`)).toBeVisible();
  }
  await page.locator('[data-action="details-next"]').click();
  for (const key of ["clinic", "age_group", "sex"]) await expect(requiredError(page, key)).toBeVisible();
  await pickDetail(page, "clinic", "Dental");
  await pickDetail(page, "age_group", "31-45");
  await pickDetail(page, "sex", "Female");
  await page.locator('[data-action="details-next"]').click();
  await expectStep(page, "questions");
  await expect(page.locator("#idStrip")).toBeHidden();
});

test("Back walks the steps in reverse", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await pickDetail(page, "clinic", "ENT");
  await page.locator('[data-action="details-next"]').click();
  await rate(page, 5);
  await activeCard(page).getByRole("button", { name: "Back" }).click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", "information_signage");
  // The answer is kept, and Next moves on.
  await expect(activeCard(page).locator('input[value="5"]')).toBeChecked();
  await activeCard(page).getByRole("button", { name: "Back" }).click();
  await expectStep(page, "details");
  await activeStep(page).getByRole("button", { name: "Back" }).click();
  await expectStep(page, "identify");
});

test("Reset clears the answers and returns to question 1, keeping the UHID and details", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await pickDetail(page, "clinic", "ENT");
  await page.locator('[data-action="details-next"]').click();
  await rate(page, 5);
  await rate(page, 4);
  await rate(page, 3);
  await headerNav(page).getByRole("link", { name: "Reset" }).click();

  await expect(activeCard(page).locator("[data-counter]")).toHaveText("Question 1 of 10", shown);
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(0);
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
  await expect(page.locator('input[name="clinic"][value="ent"]')).toBeChecked();
  await expect(page).toHaveURL(formUrl("opd")); // in place, no reload
});

test("changing the UHID from the review comes back to the review", async ({ page }) => {
  await opdToReview(page);
  await page.locator("#idStrip").click();
  await expectStep(page, "uhid");
  await page.locator('#keypad [data-key="clear"]').click();
  for (const digit of "98765432100") await page.locator(`#keypad [data-key="${digit}"]`).click();
  await page.locator('[data-action="uhid-continue"]').click();
  await expectStep(page, "review");
  await expect(page.locator("#idStripValue")).toHaveText("987 6543 2100");

  // Switching to guest asks the guest-only questions first, then returns.
  await page.locator("#idStrip").click();
  await page.locator('[data-step="uhid"] [data-action="guest"]').click();
  await expectStep(page, "details");
  await pickDetail(page, "age_group", "Over 60");
  await pickDetail(page, "sex", "Male");
  await page.locator('[data-action="details-next"]').click();
  await expectStep(page, "review");
  await expect(reviewRow(page, "Age group")).toContainText("Over 60");
});

test("a keyboard-mode QR scanner identifies the patient on the first screen", async ({ page }) => {
  await page.goto(formUrl("opd", "lang=en&scan=scanner"));
  await expectStep(page, "identify");
  await page.keyboard.type("UHID:123-4567-8901", { delay: 5 });
  await page.keyboard.press("Enter");
  await expectStep(page, "details");
  await expect(page.locator("#idStripValue")).toHaveText("123 4567 8901");
});

test("a wrong UHID length is refused", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  for (const digit of "12345") await page.locator(`#keypad [data-key="${digit}"]`).click();
  await page.locator('[data-action="uhid-continue"]').click();
  await expectStep(page, "uhid");
  await expect(page.locator("#uhidErr")).toBeVisible();
});

test("a future admission date is refused before the questions", async ({ page }) => {
  await page.goto(formUrl("ipd"));
  await enterUhid(page);
  await pickDetail(page, "ward", "General Surgery");
  const date = activeStep(page).locator('input[type="date"]');
  await date.fill(isoDate(2));
  await page.locator('[data-action="details-next"]').click();
  await expectStep(page, "details");
  await expect(activeStep(page).locator("[data-error-date]")).toHaveText("Choose today or an earlier date.", shown);
  await expect(requiredError(page, "date_of_admission")).toBeHidden();
  await date.fill(isoDate(-3));
  await page.locator('[data-action="details-next"]').click();
  await expectStep(page, "questions");
});

test("Home from a question goes back to the chooser", async ({ page }) => {
  await page.goto(chooserUrl());
  await page.getByRole("link", { name: /Inpatient feedback/ }).click();
  await continueAsGuest(page);
  await pickDetail(page, "ward", "ICU / HDU");
  await activeStep(page).locator('input[type="date"]').fill(isoDate(-1));
  await pickDetail(page, "age_group", "46-60");
  await pickDetail(page, "sex", "Other");
  await page.locator('[data-action="details-next"]').click();
  await headerNav(page).getByRole("link", { name: "Home" }).click();
  await expect(page).toHaveURL(chooserUrl());
});
