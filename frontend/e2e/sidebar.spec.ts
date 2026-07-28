import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, OWNER_EMAIL } from "./helpers";

/**
 * The column is the whole chrome now.
 *
 * Search, language, theme, the organization and the account used to live in a
 * top bar. They are all in the sidebar, and above `md` there is no top bar at
 * all — so every one of those controls is now reachable from exactly one place,
 * and a mistake in the move does not degrade the layout, it removes the ability
 * to switch organization or sign out.
 *
 * The organization is the one worth the most attention. Nothing about picking
 * the wrong one looks like an error: the agents, the keys and the run history
 * all render, they are simply somebody else's.
 */

test.use({ storageState: AUTH_STATE });

/** A second organization, so "switch" has somewhere to switch to. */
const SECOND_ORG = "E2E Second Org";

const ORG_SWITCHER = /^Organization:/;

/** The persistent column. `<aside>` is the only complementary landmark here. */
function column(page: Page) {
  return page.getByRole("complementary");
}

test.describe("Sidebar", () => {
  test("carries every control the top bar used to, and the top bar is gone", async ({ page }) => {
    await page.goto("/dashboard");

    const sidebar = column(page);
    await expect(sidebar.getByRole("button", { name: ORG_SWITCHER })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "Search" })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "Language" })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: /^Switch theme/ })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: new RegExp(OWNER_EMAIL) })).toBeVisible();

    // The point of the move: a 56px strip carrying one logo, on every page, is
    // vertical space nothing was buying.
    await expect(page.getByRole("banner")).toBeHidden();
  });

  test("search opens the palette ⌘K opens, not a second search", async ({ page }) => {
    await page.goto("/dashboard");

    await column(page).getByRole("button", { name: "Search" }).click();

    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  });

  test("switching organization from the column is a real selection", async ({ page }) => {
    // Established on entry rather than cleaned up afterwards: a run that fails
    // half way leaves the next one a working starting point, and bootstrap only
    // ever creates the owner's personal organization.
    await ensureSecondOrganization(page);

    await page.goto("/dashboard");
    const trigger = column(page).getByRole("button", { name: ORG_SWITCHER });
    await expect(trigger).toBeVisible();

    await trigger.click();
    await page.getByRole("menuitem", { name: SECOND_ORG }).click();
    await expect(trigger).toContainText(SECOND_ORG);

    // Everything org-scoped reads the selection back on the next page load, so
    // a label that changes and a selection that took are different things. The
    // reload is what tells them apart.
    await page.reload();
    await expect(column(page).getByRole("button", { name: ORG_SWITCHER })).toContainText(
      SECOND_ORG,
    );
  });

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("keeps the same controls in the slide-over", async ({ page }) => {
      // Below `md` the column is a drawer and the header survives to open it.
      // If the moved controls had not come with it, a phone would have no way
      // to switch organization or sign out at all.
      await page.goto("/dashboard");

      const header = page.getByRole("banner");
      await expect(header).toBeVisible();
      await expect(visible(page, ORG_SWITCHER)).toHaveCount(0);

      await header.getByRole("button", { name: "Toggle menu" }).click();

      // The two that exist nowhere else on a phone. Search is deliberately not
      // asserted here: the bottom tab bar has always carried its own entrance
      // to the same palette, so counting them proves nothing about the drawer.
      await expect(visible(page, ORG_SWITCHER)).toHaveCount(1);
      await expect(visible(page, new RegExp(OWNER_EMAIL))).toHaveCount(1);
    });
  });
});

/**
 * The buttons on screen with this name.
 *
 * Both surfaces are in the DOM at every viewport — one of them display:none —
 * so a plain role query matches twice and says nothing about which one a phone
 * can actually reach.
 */
function visible(page: Page, name: string | RegExp) {
  return page.getByRole("button", { name }).locator("visible=true");
}

/** Create the second organization through the product, unless it is already there. */
async function ensureSecondOrganization(page: Page): Promise<void> {
  const response = await page.request.get("/api/orgs");
  expect(response.ok(), `/api/orgs answered ${response.status()}`).toBe(true);
  const { items } = (await response.json()) as { items: { name: string }[] };
  if (items.some((org) => org.name === SECOND_ORG)) return;

  await page.goto("/orgs?create=1");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Organization name").fill(SECOND_ORG);
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(dialog).toBeHidden();
}
