import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { activeStep, chooserUrl, expectStep, needsFacility, pickDetail, rate } from "./helpers";

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
    const clipped = [...document.querySelectorAll(".btn, .opt, .chip-face, .rate, .row, .navbtn, .langbtn, .ynbtn, .key")]
      .filter(visible)
      .filter((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
      .map(describe);
    const small = [...document.querySelectorAll(".btn, .opt, .chip-face, .rate, .row, .navbtn, .langbtn, .ynbtn, .key")]
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

test("every screen fits", async ({ page }, testInfo) => {
  await page.goto(chooserUrl());
  await checkLayout(page, testInfo, "01-chooser", { fits: true });

  await page.getByRole("link", { name: /OPD feedback/ }).click();
  await expectStep(page, "identify");
  await checkLayout(page, testInfo, "02-identify", { fits: true });

  await page.getByRole("button", { name: /Enter UHID manually/ }).click();
  for (const digit of "1234567") await page.locator(`#keypad [data-key="${digit}"]`).click();
  await checkLayout(page, testInfo, "03-uhid", { fits: true });

  await page.locator('[data-step="uhid"] [data-action="guest"]').click();
  await expectStep(page, "details");
  await page.locator('[data-action="details-next"]').click(); // show the errors
  await checkLayout(page, testInfo, "04-details-errors");
  await pickDetail(page, "clinic", "Obstetrics & Gynaecology");
  await pickDetail(page, "age_group", "Over 60");
  await pickDetail(page, "sex", "Female");
  await page.locator('[data-action="details-next"]').click();

  await expectStep(page, "questions");
  await checkLayout(page, testInfo, "05-question", { fits: true });
  for (let i = 0; i < 10; i++) await rate(page, [5, 4, 3, 2, 1, 0][i % 6]);

  await expectStep(page, "comments");
  await activeStep(page).locator("label.yn", { hasText: "No" }).click();
  await activeStep(page).getByPlaceholder("Why? (optional)").fill("The queue at the pharmacy was very long today");
  await checkLayout(page, testInfo, "06-comments");
  await page.locator('[data-action="comments-next"]').click();

  await expectStep(page, "review");
  await checkLayout(page, testInfo, "07-review");
  await page.getByRole("button", { name: "Submit feedback" }).click();

  await expect(page.locator(".token")).toBeVisible();
  await checkLayout(page, testInfo, "08-done", { fits: true });
});
