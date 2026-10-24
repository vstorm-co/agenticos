import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import { OWNER_EMAIL, OWNER_PASSWORD } from "./helpers";

async function expectTouchTarget(control: Locator) {
  await expect(control).toBeVisible();
  const box = await control.boundingBox();
  expect(box?.width).toBeGreaterThanOrEqual(44);
  expect(box?.height).toBeGreaterThanOrEqual(44);
}

async function expectContained(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBe(0);
  const main = page.locator("main");
  await expect(main).toBeVisible();
  expect((await main.boundingBox())?.y).toBeGreaterThanOrEqual(0);
}

for (const platform of ["ios", "android"] as const) {
  test.describe(`${platform} surfaces`, () => {
    test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((platform) => {
        window.__AGENTICOS_SHELL__ = {
          platform,
          window: "main",
          version: "0.1.0",
          vibrancy: false,
        };
        document.addEventListener("DOMContentLoaded", () => {
          // Exercise the layout contracts around a notch/status bar and home indicator.
          document.documentElement.style.setProperty(
            "--shell-inset-top",
            platform === "ios" ? "54px" : "28px",
          );
          document.documentElement.style.setProperty("--shell-inset-bottom", "24px");
        });
      }, platform);
      await page.goto("/login");
      await expect(page.getByRole("dialog", { name: "We use cookies" })).toHaveCount(0);
      await page.getByLabel("Email", { exact: true }).fill(OWNER_EMAIL);
      await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
      await page.getByRole("button", { name: "Login", exact: true }).tap();
      await expect(page).toHaveURL(/\/dashboard(?:\?.*)?$/, { timeout: 30_000 });
    });

    test("keeps core navigation, menus and phone actions reachable", async ({ page }) => {
      test.setTimeout(60_000);
      await expectTouchTarget(page.getByRole("button", { name: "Me", exact: true }));
      const dismiss = page.getByRole("button", { name: /^Hide the tip/ }).first();
      if (await dismiss.count()) {
        await expectTouchTarget(dismiss);
        await expect(dismiss).toHaveCSS("opacity", "1");
      }
      await page.goto("/agents");
      const more = page.getByRole("button", { name: /^More actions for/ }).first();
      await expectTouchTarget(more);
      await more.tap();
      await expect(page.getByRole("menu")).toBeVisible();
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "New agent", exact: true }).tap();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expectContained(page);
      await dialog.getByRole("button", { name: "Cancel", exact: true }).tap();
      await expect(dialog).toBeHidden();

      await page.goto("/chat");
      const picker = page.getByRole("button", { name: /^Agent:/ });
      await expectTouchTarget(picker);
      await picker.tap();
      await expect(page.getByRole("radiogroup")).toBeVisible();
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Add to message", exact: true }).tap();
      await expect(
        page.getByRole("dialog").getByRole("button", { name: "Files", exact: true }),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expectContained(page);
    });

    test("uses touch targets throughout settings and preserves the viewport", async ({ page }) => {
      test.setTimeout(60_000);
      await page.goto("/settings/profile");
      await expectTouchTarget(page.getByRole("radio", { name: "Automatic colour", exact: true }));
      const theme = page
        .locator('[data-tour="settings-appearance"]')
        .getByRole("radio", { name: "Dark", exact: true });
      await theme.scrollIntoViewIfNeeded();
      await expectTouchTarget(theme);
      await theme.tap();
      await expect(theme).toBeChecked();
      await expectContained(page);
      await page.goto("/settings/notifications");
      const switches = page.getByRole("switch");
      await expect(switches.first()).toBeVisible();
      for (const control of await switches.all()) await expectTouchTarget(control);
      await expectContained(page);
      await page.goto("/settings/mcp");
      const browser = page.getByRole("radio", { name: "Through the browser", exact: true });
      await browser.scrollIntoViewIfNeeded();
      await expectTouchTarget(browser);
      const copy = page.getByRole("button", { name: "Copy", exact: true }).first();
      await expectTouchTarget(copy);
      await expectContained(page);
    });
  });
}
