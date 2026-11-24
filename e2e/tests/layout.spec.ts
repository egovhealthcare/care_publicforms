import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { activeStep, chooserUrl, expectStep, needsFacility, otherLanguage, pickValue, rate } from "./helpers";

test.beforeEach(needsFacility);

// Screens a kiosk TV shows without scrolling (the comments and review steps may scroll).
const TV_PROJECTS = ["tv-1080p", "tv-540p", "portrait"];
// Touch screens held close: targets at least 24 CSS px (WCAG 2.5.8).
const TOUCH_PROJECTS = ["tablet", "phone"];

async function checkLayout(page: Page, testInfo: TestInfo, name: string, { fits = false } = {}) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(450); // entrance animations
  const metrics = await page.evaluate(() => {
    const shell = document.querySelector(".shell")!.getBoundingClientRect();
    const visible = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const describe = (el: Element) =>
      `${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${(el.textContent || "").trim().slice(0, 30)}"`;
    const clipped = [...document.querySelectorAll(".btn, .opt, .chip-face, .rate, .row, .navbtn, .langbtn, .ynbtn, .key, .scroll-down")]
      .filter(visible)
      .filter((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
      .map(describe);
    const small = [...document.querySelectorAll(".btn, .opt, .chip-face, .rate, .row, .navbtn, .langbtn, .ynbtn, .key, .scroll-down")]
      .filter(visible)
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.height < 24 || r.width < 24;
      })
      .map(describe);
    // Structure: unique ids, and every visible form control has a name.
    const ids = [...document.querySelectorAll("[id]")].map((el) => el.id);
    const duplicateIds = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
    const unnamed = [...document.querySelectorAll("input:not([type=hidden]), textarea, select")]
      .filter((el) => (el as HTMLInputElement).offsetParent !== null)
      .filter(
        (el) =>
          !(el as HTMLInputElement).labels?.length &&
          !el.getAttribute("aria-label") &&
          !el.getAttribute("aria-labelledby"),
      )
      .map(describe);
    const main = document.querySelector("main .step.is-active, main .screen") as HTMLElement | null;
    const cta = main?.querySelector(".qcard.is-active .btn-next, .area-nav .btn-cta, .btn-cta") as HTMLElement | null;
    return {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      left: shell.left,
      right: window.innerWidth - shell.right,
      clipped,
      small,
      duplicateIds,
      unnamed,
      ctaBottom: cta ? cta.getBoundingClientRect().bottom : null,
    };
  });
  const project = testInfo.project.name;
  await page.screenshot({ path: `screenshots/${project}/${name}.png`, fullPage: true });

  expect.soft(metrics.scrollWidth, `${name}: no sideways scrolling`).toBeLessThanOrEqual(metrics.innerWidth);
  expect.soft(Math.abs(metrics.left - metrics.right), `${name}: column centred`).toBeLessThanOrEqual(2);
  expect.soft(metrics.clipped, `${name}: text fits its controls`).toEqual([]);
  expect.soft(metrics.duplicateIds, `${name}: ids are unique`).toEqual([]);
  expect.soft(metrics.unnamed, `${name}: form controls have a name`).toEqual([]);
  if (TOUCH_PROJECTS.includes(project)) {
    expect.soft(metrics.small, `${name}: touch targets ≥ 24px`).toEqual([]);
  }
  if (fits && TV_PROJECTS.includes(project) && metrics.ctaBottom !== null) {
    expect.soft(metrics.ctaBottom, `${name}: main button on screen without scrolling`).toBeLessThanOrEqual(
      metrics.innerHeight,
    );
  }
}

/** Walks every screen of an OPD guest, checking each, in the screen language `lang`. */
async function walkScreens(page: Page, testInfo: TestInfo, lang: string) {
  const check = (name: string, options?: { fits?: boolean }) =>
    checkLayout(page, testInfo, lang === "en" ? name : `${lang}/${name}`, options);
  await page.goto(chooserUrl(`lang=${lang}`));
  await check("01-chooser", { fits: true });

  await page.locator('a.opt--form[href*="/type/opd/"]').click();
  await expectStep(page, "identify");
  await check("02-identify", { fits: true });

  await page.locator('[data-step="identify"] [data-go="uhid"]').click();
  for (const digit of "1234567") await page.locator(`#keypad [data-key="${digit}"]`).click();
  await check("03-uhid", { fits: true });

  await page.locator('[data-step="uhid"] [data-action="guest"]').click();
  await expectStep(page, "screen-1");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click(); // show the errors
  await check("04-details-errors");
  await pickValue(page, "clinic", "obstetrics_gynaecology");
  await pickValue(page, "age_group", "over_60");
  await pickValue(page, "sex", "female");
  await page.locator('[data-step="screen-1"] [data-action="screen-next"]').click();

  await expectStep(page, "questions");
  await check("05-question", { fits: true });
  for (let i = 0; i < 10; i++) await rate(page, [5, 4, 3, 2, 1, 0][i % 6]);

  await expectStep(page, "screen-3");
  await activeStep(page).locator('label.yn:has(input[value="no"])').click();
  await activeStep(page).locator("textarea[data-comment]").fill("The queue at the pharmacy was very long today");
  await check("06-comments");
  await page.locator('[data-step="screen-3"] [data-action="screen-next"]').click();

  await expectStep(page, "review");
  await check("07-review");
  await page.locator('[data-step="review"] button[value="submit"]').click();

  await expect(page.locator(".token")).toBeVisible();
  await check("08-done", { fits: true });
}

test("every screen fits", async ({ page }, testInfo) => {
  await walkScreens(page, testInfo, "en");
});

test("every screen fits in the other language", async ({ page }, testInfo) => {
  await page.goto(chooserUrl());
  const language = await otherLanguage(page); // its words may be longer, its letters taller
  await walkScreens(page, testInfo, language.code);
});
