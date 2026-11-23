import { expect, test, type Locator, type Page } from "@playwright/test";

export const facilityId = process.env.PF_FACILITY_ID ?? "";
export const UHID = "12345678901";

/** Use in each spec: test.beforeEach(needsFacility). */
export function needsFacility(): void {
  test.skip(!facilityId, "Set PF_FACILITY_ID to a facility's external id");
}

/** The form chooser, by default as an English screen. */
export function chooserUrl(query = "lang=en"): string {
  return `/facility/${facilityId}/public_forms/${query ? `?${query}` : ""}`;
}

/** A screen pinned to one form, by default as an English screen. */
export function formUrl(code: string, query = "lang=en"): string {
  return `/facility/${facilityId}/public_forms/type/${code}/form/${query ? `?${query}` : ""}`;
}

export function activeStep(page: Page): Locator {
  return page.locator("section.step.is-active");
}

export async function expectStep(page: Page, name: string): Promise<void> {
  await expect(activeStep(page)).toHaveAttribute("data-step", name);
}

export function headerNav(page: Page): Locator {
  return page.locator("#hdrNav");
}

/** The question on screen, e.g. "Question 3 of 10". */
export function activeCard(page: Page): Locator {
  return page.locator("[data-card].is-active");
}

/** Identify with a UHID typed on the on-screen keypad. */
export async function enterUhid(page: Page, uhid = UHID): Promise<void> {
  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  await expectStep(page, "uhid");
  await page.locator('#keypad [data-key="clear"]').click();
  for (const digit of uhid) await page.locator(`#keypad [data-key="${digit}"]`).click();
  await page.locator('[data-action="uhid-continue"]').click();
}

export async function continueAsGuest(page: Page): Promise<void> {
  await page.getByRole("button", { name: /Continue as guest/ }).click();
}

/**
 * Pick an option on the details step by its English label, e.g.
 * pickDetail(page, "clinic", "ENT"). Every string is in the page in each
 * language, so match the visible text exactly.
 */
export async function pickDetail(page: Page, key: string, label: string): Promise<void> {
  await activeStep(page).locator(`[data-question-key="${key}"]`).getByText(label, { exact: true })
    .filter({ visible: true })
    .click();
}

/** The visible text of an element (each string is in the page in every language). */
export const shown = { useInnerText: true } as const;

/** The "needs an answer" message under a question. */
export function requiredError(page: Page, key: string): Locator {
  return page.locator(`[data-question-key="${key}"] [data-error]`);
}

/** Pick an option by its stored value, whatever the language, e.g. pickValue(page, "clinic", "ent"). */
export async function pickValue(page: Page, key: string, value: string): Promise<void> {
  await activeStep(page).locator(`[data-question-key="${key}"] label:has(input[value="${value}"])`).click();
}

/** Tap a rating (5 = best … 1, 0 = no comments) and wait for the kiosk to move on. */
export async function rate(page: Page, value: number): Promise<void> {
  const card = activeCard(page);
  const key = await card.getAttribute("data-question-key");
  await card.locator(`label.rate-option:has(input[value="${value}"])`).click();
  await expect(page.locator(`[data-card][data-question-key="${key}"]`)).toBeHidden();
}

/** Answer every rating card shown, all with the same value. */
export async function rateAll(page: Page, value = 4): Promise<number> {
  await expectStep(page, "questions");
  const total = await page.locator("[data-card]:not([hidden])").count();
  for (let i = 0; i < total; i++) await rate(page, value);
  return total;
}

/** Identified OPD patient up to the review: UHID, ENT clinic, every rating 4, no open answers. */
export async function opdToReview(page: Page, query = "lang=en"): Promise<void> {
  await page.goto(formUrl("opd", query));
  await enterUhid(page);
  await expectStep(page, "screen-1");
  await pickDetail(page, "clinic", "ENT");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click();
  await rateAll(page);
  await expectStep(page, "screen-3");
  await page.locator('[data-step="screen-3"] [data-action="screen-next"]').click();
  await expectStep(page, "review");
}

export function reviewRow(page: Page, label: string): Locator {
  return page.locator("#reviewRows .row", { has: page.locator(".row-label", { hasText: label }) });
}

/** A yyyy-mm-dd date `days` from today, in the browser's local time. */
export function isoDate(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * The first language the screen offers besides English, whichever the
 * backend's LANGUAGES has, with its header button and `text(selector)`: that
 * element's text in the language (every page carries each language's text).
 * Skips the test when only English is offered.
 */
export async function otherLanguage(
  page: Page,
): Promise<{ code: string; button: Locator; text: (selector: string) => Promise<string> }> {
  const button = page.locator('[data-set-lang]:not([data-set-lang="en"])').first();
  test.skip((await button.count()) === 0, "The backend's LANGUAGES has only English");
  const code = (await button.getAttribute("data-set-lang")) ?? "";
  const text = async (selector: string) =>
    ((await page.locator(`${selector} .l10n--${code}`).first().textContent()) ?? "").trim();
  return { code, button, text };
}
