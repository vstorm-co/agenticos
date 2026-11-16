import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

async function activeOrganization(page: Page): Promise<string> {
  const read = () =>
    page.evaluate(() => {
      const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
      if (!value || typeof value !== "object" || !("state" in value)) return "";
      const state = value.state;
      return state &&
        typeof state === "object" &&
        "activeOrgId" in state &&
        typeof state.activeOrgId === "string"
        ? state.activeOrgId
        : "";
    });
  await expect.poll(read).not.toBe("");
  return read();
}

test.describe("voice provider catalog", () => {
  test.use({ storageState: AUTH_STATE, viewport: { width: 1280, height: 900 } });

  test("offers ElevenLabs Scribe without changing saved organization settings", async ({
    page,
  }, testInfo) => {
    await page.goto("/dashboard");
    const orgId = await activeOrganization(page);
    await page.goto(`/orgs/${orgId}/members?tab=voice`);
    const provider = page.getByRole("combobox", { name: "Provider", exact: true });
    await expect(provider).toBeVisible();
    const previous = await provider.innerText();
    await provider.click();
    await page.getByRole("option", { name: "ElevenLabs", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Model", exact: true })).toContainText(
      "Scribe v3",
    );
    await page.screenshot({ path: testInfo.outputPath("elevenlabs-scribe.png"), fullPage: true });
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(provider).toHaveText(previous);
  });
});

async function expectGeometry(first: Locator, second: Locator, touch: boolean): Promise<void> {
  await expect(first).toBeVisible();
  await expect(second).toBeVisible();
  await expect
    .poll(async () => {
      const [left, right] = await Promise.all([first.boundingBox(), second.boundingBox()]);
      if (!left || !right) return Infinity;
      return Math.max(
        Math.abs(left.height - right.height),
        touch ? Math.abs(left.x - right.x) : Math.abs(left.y - right.y),
      );
    })
    .toBeLessThan(1);
  await expect
    .poll(async () => {
      const bounds = await first.boundingBox();
      return bounds ? Math.round(bounds.height * 100) / 100 : 0;
    })
    .toBeGreaterThanOrEqual(touch ? 44 : 40);
}

for (const touch of [false, true]) {
  test.describe(touch ? "touch form layout" : "desktop form layout", () => {
    test.use({
      storageState: AUTH_STATE,
      viewport: { width: touch ? 390 : 1280, height: 900 },
      hasTouch: touch,
      isMobile: touch,
    });
    test("help text and native inputs do not displace adjacent controls", async ({ page }) => {
      await page.goto("/dashboard");
      const orgId = await activeOrganization(page);
      await page.goto(`/orgs/${orgId}/members?tab=voice`);
      const provider = page.locator("#org-voice-provider");
      await expect(provider).toBeVisible();
      const model = page.locator("#org-voice-model");
      await expectGeometry(
        provider,
        (await model.count()) ? model : page.locator("#org-voice-language"),
        touch,
      );
      await page.goto("/sandboxes");
      await page.getByRole("button", { name: "Add connection", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Add sandbox connection" });
      await expectGeometry(
        dialog.getByRole("textbox", { name: "Name", exact: true }),
        dialog.getByRole("combobox", { name: "Kind", exact: true }),
        touch,
      );
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    });
  });
}
