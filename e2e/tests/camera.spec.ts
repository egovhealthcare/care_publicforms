import { expect, test, type Page } from "@playwright/test";
import { expectStep, formUrl, needsFacility } from "./helpers";

test.beforeEach(needsFacility);

// "Scan the QR" is offered only while camera scanning can work. These tests
// stand in for the browser's camera APIs before the page loads.
type Camera = {
  readsQr?: boolean; // BarcodeDetector exists and reads QR codes
  cameras?: number; // connected cameras
  permission?: "granted" | "prompt" | "denied";
  onOpen?: "ok" | "NotAllowedError" | "NotFoundError"; // what getUserMedia does
};

async function fakeCamera(page: Page, camera: Camera) {
  const options = { readsQr: true, cameras: 1, permission: "granted", onOpen: "ok", ...camera };
  await page.addInitScript((o) => {
    const w = window as unknown as Record<string, unknown>;
    w.BarcodeDetector = o.readsQr
      ? class {
          static async getSupportedFormats() {
            return ["qr_code"];
          }
          async detect() {
            return [];
          }
        }
      : undefined;
    const devices = Array.from({ length: o.cameras }, (_, i) => ({
      kind: "videoinput",
      deviceId: String(i),
      groupId: "",
      label: "",
    }));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: async () => devices,
        getUserMedia: async () => {
          if (o.onOpen !== "ok") throw new DOMException("Camera unavailable", o.onOpen);
          return new MediaStream();
        },
        addEventListener() {},
      },
    });
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (async (descriptor: PermissionDescriptor) =>
      descriptor.name === ("camera" as PermissionName)
        ? { state: o.permission, onchange: null }
        : query(descriptor)) as typeof navigator.permissions.query;
  }, options);
}

const scanOption = (page: Page) => page.locator('.opt[data-go="scan"]');

test("Scan is offered when the camera can be used", async ({ page }) => {
  await fakeCamera(page, {});
  await page.goto(formUrl("opd"));
  await expect(scanOption(page)).toBeVisible();
  await scanOption(page).click();
  await expectStep(page, "scan");
});

for (const [name, camera] of [
  ["camera permission is denied", { permission: "denied" }],
  ["there is no camera", { cameras: 0 }],
  ["the browser can't read QR codes", { readsQr: false }],
] as [string, Camera][]) {
  test(`Scan is hidden when ${name}`, async ({ page }) => {
    await fakeCamera(page, camera);
    await page.goto(formUrl("opd"));
    await expect(page.getByRole("button", { name: /Enter UHID manually/ })).toBeVisible();
    await expect(scanOption(page)).toBeHidden();
  });
}

for (const onOpen of ["NotAllowedError", "NotFoundError"] as const) {
  test(`a scan that fails (${onOpen}) hides Scan and goes to typing the UHID`, async ({ page }) => {
    await fakeCamera(page, { permission: "prompt", onOpen });
    await page.goto(formUrl("opd"));
    await scanOption(page).click();
    await expectStep(page, "uhid");
    await expect(scanOption(page)).toHaveAttribute("hidden", "");
  });
}

test("a keyboard-mode scanner doesn't need a camera", async ({ page }) => {
  await fakeCamera(page, { cameras: 0 });
  await page.goto(formUrl("opd", "lang=en&scan=scanner"));
  await expect(scanOption(page)).toBeVisible();
});
