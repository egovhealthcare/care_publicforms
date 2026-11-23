import { expect, test } from "@playwright/test";
import {
  activeCard,
  activeStep,
  enterUhid,
  expectStep,
  formUrl,
  needsFacility,
  opdToOpenQuestions,
  opdToReview,
  pickDetail,
  rate,
  trackDialogs,
} from "./helpers";

test.beforeEach(needsFacility);

// What keeps a shared screen safe and forgiving: the next patient never sees
// the previous one's answers, and a slip doesn't lose what was entered.

test("Back after the thank-you page doesn't bring it back", async ({ page }) => {
  await opdToReview(page);
  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page).toHaveURL(/\/done\/\?.*ref=/);
  await page.getByRole("link", { name: /another|start/i }).click();
  await expectStep(page, "identify");

  // "Start new" replaced the thank-you page in the history.
  await page.goBack();
  await expect(page).not.toHaveURL(/\/done\//);
  await expect(page.locator(".token")).toHaveCount(0);
  await expect(page.locator("#feedback input:checked")).toHaveCount(0); // a fresh form, no answers
});

test("leaving with answers asks first; leaving an untouched form doesn't", async ({ context }) => {
  // Touched (a tap lets the browser ask), but nothing entered: closes without asking.
  const untouched = await context.newPage();
  await untouched.goto(formUrl("opd"));
  await untouched.locator(".hero-title").click();
  const asked = trackDialogs(untouched);
  await untouched.close({ runBeforeUnload: true });
  await expect.poll(() => untouched.isClosed()).toBe(true);
  expect(asked).toEqual([]);

  // With a UHID entered, closing or reloading asks with the browser's "Leave site?".
  const started = await context.newPage();
  await started.goto(formUrl("opd"));
  await enterUhid(started);
  const dialog = started.waitForEvent("dialog");
  await started.close({ runBeforeUnload: true });
  expect((await dialog).type()).toBe("beforeunload");
  await (await dialog).accept();
});

test("characters that could carry code can't be typed", async ({ page }) => {
  await opdToOpenQuestions(page);
  const box = activeStep(page).getByLabel("What would you most like to see improved?");
  await box.pressSequentially("Wait <10 mins> please {now}");
  await expect(box).toHaveValue("Wait 10 mins please now");
  await expect(activeStep(page).locator('[data-question-key="improvement"] [data-error-characters]')).toBeVisible();
});

test("changing the UHID part-way keeps the answers and the place", async ({ page }) => {
  await page.goto(formUrl("opd"));
  await enterUhid(page);
  await pickDetail(page, "clinic", "ENT");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click();
  for (const value of [5, 4, 3, 2]) await rate(page, value);
  const here = await activeCard(page).getAttribute("data-question-key");

  // Another UHID: straight back to the same question, every answer kept.
  await page.locator("#idStrip").click();
  await expectStep(page, "uhid");
  await page.locator('#keypad [data-key="clear"]').click();
  for (const digit of "98765432100") await page.locator(`#keypad [data-key="${digit}"]`).click();
  await page.locator('[data-action="uhid-continue"]').click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", here ?? "");
  await expect(page.locator("[data-step=questions] input:checked")).toHaveCount(4);

  // As a guest: first the guest-only questions, then the same question again.
  await page.locator("#idStrip").click();
  await page.locator('[data-step="uhid"] [data-action="guest"]').click();
  await expectStep(page, "screen-1");
  await expect(page.locator('input[name="clinic"][value="ent"]')).toBeChecked();
  await pickDetail(page, "age_group", "31-45");
  await pickDetail(page, "sex", "Female");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click();
  await expect(activeCard(page)).toHaveAttribute("data-question-key", here ?? "");
});

test("on a short screen a box stops clear of the pinned buttons", async ({ page }) => {
  await opdToOpenQuestions(page);
  await page.setViewportSize({ width: 390, height: 360 }); // a landscape phone, or a tablet with its keyboard up
  await page.evaluate(() => window.scrollTo(0, 0));
  const last = activeStep(page).locator("textarea:not([data-comment])").last();
  await last.focus(); // the browser scrolls it into view, as a tap would
  const box = await last.boundingBox();
  const buttons = await activeStep(page).locator(".area-nav .btn").first().boundingBox();
  expect(box && buttons).toBeTruthy();
  expect(box!.y + box!.height).toBeLessThanOrEqual(buttons!.y + 1);
});

test("with JavaScript there is no countdown; the idle reset follows touches", async ({ page }) => {
  await page.goto(formUrl("opd", "lang=en&from=start")); // a page holding the patient's choice of form
  await expectStep(page, "identify");
  await expect(page.locator(".tick-timer")).toHaveCount(0); // only without JavaScript
  await expect(page.locator("body")).toHaveAttribute("data-idle-timeout", "90");
});
