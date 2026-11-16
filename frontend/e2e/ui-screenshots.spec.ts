import { expect, test } from "./fixtures";

import { AUTH_STATE, LIVE_RECORD_TITLE, LIVE_TABLE_NAME, rowsAt } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Review screenshots of the chat screen at desktop and phone widths.
 *
 * Frontend pull requests need before and after screenshots of the running app.
 * CI uploads `test-results/` from every E2E shard, so the images land in the
 * `playwright-results-*` artifacts: run on `t3` for "before", on the pull
 * request for "after". The test asserts only that the chat loaded.
 */
const WIDTHS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

test.describe("Review screenshots", () => {
  for (const size of WIDTHS) {
    test(`captures the chat at ${size.name} width`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto("/chat");
      await expect(page.getByText("Live")).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath(`chat-${size.name}.png`),
        fullPage: false,
      });
    });

    test(`captures coding accounts at ${size.name} width`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto("/settings/profile");
      const section = page.locator('[data-tour="personal-coding-accounts"]');
      await expect(section).toBeVisible();
      await section.scrollIntoViewIfNeeded();
      await section.screenshot({
        path: testInfo.outputPath(`coding-accounts-${size.name}.png`),
      });
    });

    test(`captures a table at ${size.name} width`, async ({ page }, testInfo) => {
      const tables = await rowsAt(page.request, "/api/tables");
      const table = tables.find((row) => row.name === LIVE_TABLE_NAME);
      expect(table, "the seeded live table exists").toBeTruthy();
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto(`/tables/${String(table!.id)}`);
      await expect(page.getByText(LIVE_RECORD_TITLE).first()).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath(`table-${size.name}.png`),
        fullPage: false,
      });
    });
  }
});
