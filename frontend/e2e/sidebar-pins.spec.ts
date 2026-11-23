import { expect, test } from "./fixtures";

import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Pinning a sidebar entry, end to end: pin from More, reload, still pinned, unpin.
 *
 * The reload is the point. Pins live on the server per user and organization, so
 * a page that kept them only in memory or in the browser would pass every unit
 * test and lose them here. The spec starts by clearing its own pin, because the
 * database outlives a run.
 */
test.describe("Sidebar pins", () => {
  test("pins from More, keeps the pin across a reload, then unpins", async ({ page }) => {
    await page.goto("/dashboard");
    const sidebar = page.getByRole("navigation", { name: "Primary" });
    const more = page.getByRole("dialog", { name: "More" });
    const openMore = async () => {
      await sidebar.getByRole("button", { name: "More", exact: true }).click();
      await expect(more).toBeVisible();
    };
    const closeMore = async () => {
      await page.keyboard.press("Escape");
      await expect(more).toBeHidden();
    };
    const pin = () => more.getByRole("button", { name: /^(Pin|Unpin) Skills$/ });

    await openMore();
    if ((await pin().getAttribute("aria-pressed")) === "true") await pin().click();
    await closeMore();
    await expect(sidebar.getByRole("link", { name: "Skills" })).toHaveCount(0);

    // Pinning does not navigate and does not close the panel.
    await openMore();
    await more.getByRole("button", { name: "Pin Skills" }).click();
    await expect(pin()).toHaveAttribute("aria-pressed", "true");
    await expect(more).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard$/);
    await closeMore();
    await expect(sidebar.getByRole("link", { name: "Skills" })).toBeVisible();

    await page.reload();
    await expect(sidebar.getByRole("link", { name: "Skills" })).toBeVisible();

    await openMore();
    await more.getByRole("button", { name: "Unpin Skills" }).click();
    await closeMore();
    await expect(sidebar.getByRole("link", { name: "Skills" })).toHaveCount(0);

    await page.reload();
    await expect(sidebar.getByRole("link", { name: "Chat" })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Skills" })).toHaveCount(0);
  });
});
