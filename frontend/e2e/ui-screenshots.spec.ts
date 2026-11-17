import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  LIVE_RECORD_TITLE,
  LIVE_TABLE_NAME,
  SEEDED_AGENT_NAME,
  rowsAt,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Review screenshots of the chat screen at desktop and phone widths.
 *
 * Frontend pull requests need before and after screenshots of the running app.
 * CI uploads `test-results/` from every E2E shard, so the images land in the
 * `playwright-results-*` artifacts: run on `t3` for "before", on the pull
 * request for "after". The editor capture also waits for the seeded agent's
 * settings to load, so its image cannot show an empty or failed read.
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
      const section = page.locator('section:has(> header[data-tour="personal-coding-accounts"])');
      await expect(section.getByText("Claude Code", { exact: true })).toBeVisible();
      await expect(section.getByText("Codex", { exact: true })).toBeVisible();
      const connect = section.getByRole("button", { name: "Connect", exact: true });
      await expect(connect).toHaveCount(2);
      await expect(connect.first()).toBeEnabled();
      await expect(connect.last()).toBeEnabled();
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

  test("captures the selected agent's settings at desktop width", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/chat?new=review-agent-settings");
    await expect(page.getByText("Live")).toBeVisible();
    await page.getByRole("button", { name: /^Agent:/ }).click();
    await page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) }).click();
    await page.getByRole("button", { name: "Open agent settings", exact: true }).click();

    const panel = page.getByRole("complementary", { name: "Agent settings", exact: true });
    await expect(panel.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(
      SEEDED_AGENT_NAME,
    );
    await expect(panel.getByRole("textbox", { name: "Instructions", exact: true })).toBeEnabled();
    await page.screenshot({
      path: testInfo.outputPath("chat-settings-desktop.png"),
      fullPage: false,
    });
  });
});
