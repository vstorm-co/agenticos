import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  SEEDED_AGENT_NAME,
  SEEDED_KB_NAME,
  SEEDED_MODEL_LABEL,
  openAgent,
  pageHeading,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * The sidebar says which section you are in, on every page of it.
 *
 * This is here rather than only in `app-sidebar.test.tsx` because that suite
 * mocks `usePathname`: it proves the matching rule against strings the test
 * chose, and nothing about that rule meeting a URL the router produced. The bug
 * it missed lived exactly in that gap — `/kb/<id>` reached the rule with its
 * `/kb` already eaten by locale stripping, so the reported page showed a sidebar
 * with nothing lit at all.
 *
 * These specs only read, so there is nothing to undo; each still opens on
 * `goto`, so no test depends on where another one left the browser.
 */

/**
 * The primary nav column.
 *
 * The mobile tab bar carries the same label but is display:none at this
 * viewport, so it is not in the accessibility tree — `toHaveCount(1)` below
 * turns any future ambiguity into a readable failure rather than a locator that
 * silently picks the wrong nav.
 */
function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Primary" });
}

/** Fail unless exactly one sidebar entry is marked, and it is `entry`. */
async function expectMarked(page: Page, entry: string): Promise<void> {
  const marked = sidebar(page).locator('[aria-current="page"]');

  // Both halves matter: none marked is the reported bug, two marked is a nav
  // entry that has begun swallowing another's section.
  await expect(marked, "the sidebar marks no section, or more than one").toHaveCount(1);
  await expect(marked).toHaveText(entry);
}

test.describe("Sidebar section marking", () => {
  test("a list page marks its own section", async ({ page }) => {
    await page.goto("/kb");

    // The seeded row, so this fails on a dark sidebar rather than on a page that
    // rendered its empty state because the request behind it failed.
    await expect(page.getByText(SEEDED_KB_NAME, { exact: true }).first()).toBeVisible();

    await expectMarked(page, "Knowledge bases");
  });

  test("a knowledge base detail page keeps Knowledge bases marked", async ({ page }) => {
    // The reported case, reached the way a user reaches it: the id in the URL is
    // a real one, so a rule that only works on paths a test made up fails here.
    await page.goto("/kb");
    // `.first()`: the seed creates its knowledge base on every run and the
    // database outlives the run, so by now there are several by that name. Which
    // one opens does not matter here — any of them is a detail page.
    await page
      .getByRole("link", { name: `Open ${SEEDED_KB_NAME}` })
      .first()
      .click();

    await expect(page).toHaveURL(/\/kb\/[0-9a-f-]{36}$/);
    await expect(pageHeading(page, SEEDED_KB_NAME)).toBeVisible();

    await expectMarked(page, "Knowledge bases");
  });

  test("an agent detail page keeps Agents marked", async ({ page }) => {
    // A second section, so the first is not passing on a coincidence.
    await openAgent(page, SEEDED_AGENT_NAME);
    await expect(page).toHaveURL(/\/agents\/[0-9a-f-]{36}$/);

    await expectMarked(page, "Agents");
  });

  test("a page reached through a redirect marks the entry it landed on", async ({ page }) => {
    // The vault used to live at /settings/providers, which now redirects. The
    // mark has to follow the destination: a rule that saw the URL that was asked
    // for, rather than the one that was served, leaves the sidebar dark here —
    // and /settings is a path no entry claims, so there is nothing to fall back
    // to.
    await page.goto("/settings/providers");
    await expect(page).toHaveURL(/\/vault$/);

    await expect(page.getByRole("main").getByText(SEEDED_MODEL_LABEL).first()).toBeVisible();

    await expectMarked(page, "Vault");
  });
});
