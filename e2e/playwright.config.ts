import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests for the patient feedback pages, run in a real browser
 * against a Care backend with the plugin installed (see ../README.md).
 *
 *   PF_FACILITY_ID  external id (UUID) of a facility on that backend (required)
 *   PF_BASE_URL     the Care backend, default http://localhost:9000
 *
 * The tests submit feedback, so point them at a development database.
 * They open every page with ?lang=en, so they pass whatever LANGUAGES and
 * DEFAULT_LANGUAGE the backend uses. The language tests use the first
 * language offered after English, and skip themselves if there is none.
 */
const desktop = devices["Desktop Chrome"];

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: process.env.CI ? 1 : 3,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.PF_BASE_URL ?? "http://localhost:9000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    // Behaviour, on a 1080p kiosk TV
    {
      name: "kiosk",
      testMatch: /(flows|language|idle|camera|guards|edges)\.spec\.ts/,
      use: { ...desktop, viewport: { width: 1920, height: 1080 } },
    },
    // The same pages without JavaScript: each step button posts the page
    {
      name: "no-js",
      testMatch: /nojs\.spec\.ts/,
      use: { ...desktop, viewport: { width: 1280, height: 900 }, javaScriptEnabled: false },
    },
    // Layout on every screen shape the kiosk runs on
    { name: "tv-1080p", testMatch: /layout\.spec\.ts/, use: { ...desktop, viewport: { width: 1920, height: 1080 } } },
    { name: "tv-540p", testMatch: /layout\.spec\.ts/, use: { ...desktop, viewport: { width: 960, height: 540 } } },
    {
      name: "portrait",
      testMatch: /layout\.spec\.ts/,
      use: { ...desktop, viewport: { width: 1080, height: 1920 } },
    },
    { name: "tablet", testMatch: /layout\.spec\.ts/, use: { ...desktop, viewport: { width: 768, height: 1024 } } },
    { name: "phone", testMatch: /layout\.spec\.ts/, use: { ...devices["Pixel 7"] } },
  ],
});
