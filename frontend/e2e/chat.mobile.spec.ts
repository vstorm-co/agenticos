import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

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

    await expect(
      page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
    ).toBeVisible();
    // Empty Inbox content stays hidden while its space remains reserved.
    const briefing = page.locator(".chat-home-inbox");
    await expect(briefing).toBeVisible();
    await expect(briefing).not.toHaveAttribute("aria-busy", "true");
    await input.tap();
    await expect(page.getByTestId("composer-hints")).toBeVisible();
    const composer = page.locator(".composer-box");
    const before = await composer.boundingBox();
    if (!before) throw new Error("Expected the live composer on screen");
    await input.pressSequentially("one");
    await expect(page.locator("[data-chat-welcome-hints]")).toBeHidden();
    expect((await composer.boundingBox())?.y).toBeCloseTo(before.y, 0);
    await input.press("Enter");
    await input.pressSequentially("two");
    // A rich editor: the newline is a <br>, which only innerText reads.
    await expect(input).toHaveText(/^one\ntwo\n?$/, { useInnerText: true });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("keeps attachments in the compact menu and dictation beside the composer", async ({
    page,
  }) => {
    await page.goto("/chat");
    await expect(page.getByText("Live")).toBeVisible();
    await expect(page.getByRole("button", { name: "Voice input", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Add to message" }).tap();
    const menu = page.locator("[data-chat-popover]");
    await expect(menu.getByRole("button", { name: "Attach file", exact: true })).toBeVisible();
  });
});
