import { expect, test } from "./fixtures";

import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * The chat on a phone (#2066).
 *
 * What a real device does with the keyboard - iOS sliding it over the page,
 * Android shrinking the layout - is not something an emulated browser
 * reproduces, so this asserts the conditions those behaviours depend on rather
 * than the behaviours: a field no smaller than iOS's zoom threshold, a page
 * that does not scroll sideways, Enter that breaks a line on a touch keyboard,
 * and the controls a thumb needs.
 */
test.describe("Chat on a phone", () => {
  test("has a composer that does not zoom, scroll sideways or send on Enter", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.getByText("Live")).toBeVisible();
    const input = page.getByRole("textbox", { name: "Type a message..." });
    await expect(input).toBeEnabled();

    const size = await input.evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    expect(size).toBeGreaterThanOrEqual(16);

    await input.tap();
    await input.pressSequentially("one");
    await input.press("Enter");
    await input.pressSequentially("two");
    await expect(input).toHaveValue("one\ntwo");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("offers attaching and dictating from one `+`, as a sheet", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.getByText("Live")).toBeVisible();

    await page.getByRole("button", { name: "Add to message" }).tap();

    const sheet = page.getByRole("dialog");
    await expect(sheet.getByRole("button", { name: "Attach file" })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Voice input" })).toBeVisible();
  });

  test("puts the tab bar away while somebody types", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.getByText("Live")).toBeVisible();
    const tabs = page.getByRole("navigation", { name: "Primary" });
    await expect(tabs).toBeVisible();

    await page.getByRole("textbox", { name: "Type a message..." }).tap();

    await expect(tabs).toBeHidden();
  });
});
