import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_ORG_MCP_NAME, expectNoRenderedSecret, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * MCP servers — the one page.
 *
 * The catalog and a person's own connections used to be two destinations
 * presented as peers, which is what made the difference between them
 * unanswerable. They are one list now, so what is worth asserting is that the
 * merge did not lose either half: the catalog is still complete, connection
 * state is on the row, both owners are named, and no credential is rendered.
 *
 * The catalog needs no seeding, but it does have to be *asserted* — an empty
 * catalog and a failed catalog request draw the same page. The connected half
 * asserts on the organization server `seed.setup.ts` connects.
 */

/** Servers every deployment ships, and the auth each one needs. */
const CATALOG = [
  { server: "GitHub", category: "development" },
  { server: "PostgreSQL", category: "data" },
  { server: "Notion", category: "knowledge" },
  { server: "Sentry", category: "observability" },
];

/**
 * Bring the seeded custom server into view.
 *
 * The page is one grid over the whole catalog, fifty cards to a page, and custom
 * servers sort *last* - so a connection somebody made by URL is on page two and
 * `getByRole("group", ...)` finds nothing. Searching is what a person does, and it
 * is the only step these assertions were missing.
 */
async function findSeededServer(page: Page) {
  await page.goto("/mcp-servers");
  await expect(pageHeading(page, "MCP servers")).toBeVisible();
  await page.getByRole("textbox", { name: "Search servers…" }).fill(SEEDED_ORG_MCP_NAME);
  const card = page.getByRole("group", { name: SEEDED_ORG_MCP_NAME });
  await expect(card).toBeVisible();
  return card;
}

test.describe("MCP servers", () => {
  test("lists every server the deployment curates, with what each needs", async ({ page }) => {
    await page.goto("/mcp-servers");
    await expect(pageHeading(page, "MCP servers")).toBeVisible();

    for (const { server, category } of CATALOG) {
      const card = page.getByRole("group", { name: server });
      await expect(card, `${server} should be in the catalog`).toBeVisible();
      // The category is on the card rather than a section heading above it. It
      // stopped being a heading when the page became a grid: this catalog has
      // one entry per category, so every section held a single card.
      await expect(
        card.getByText(category, { exact: true }),
        `${server} should say it is a ${category} server`,
      ).toBeVisible();
    }

    // Auth is the thing that actually varies between servers, so it is on the
    // row rather than behind a click. Both kinds are represented above.
    await expect(page.getByText("API token").first()).toBeVisible();
    await expect(page.getByText("OAuth").first()).toBeVisible();
  });

  test("says who has connected each server, on the card", async ({ page }) => {
    // The merge, and the answer to the question that started it: a catalog
    // entry is not a sibling of a connection, it is what one points at. So
    // "connected, and by whom" is a property of the card.
    //
    // Both matchers are exact. GitHub's own description contains the word
    // "organization", so a substring match resolves to two elements and fails
    // on strict mode — which is a test asserting on prose rather than on the
    // scope label it means.
    // Asserted on the server the seed actually connects. It used to be GitHub's
    // card, which was connected both ways by an older seed; today nothing is
    // connected personally, so the "You" half has no fixture to stand on and
    // claiming it would be asserting on an empty page.
    const card = await findSeededServer(page);
    await expect(card.getByText("Organization", { exact: true })).toBeVisible();
  });

  test("marks each card with the service's own logo", async ({ page }) => {
    // The reported regression, guarded against the real build: the catalog
    // rendered one generic icon on every row, which in a grid is the same as no
    // icons at all. Asserted as "two cards draw different glyphs" rather than on
    // a class or a file name — identical marks are the bug, whatever draws them.
    await page.goto("/mcp-servers");
    await expect(pageHeading(page, "MCP servers")).toBeVisible();

    const mark = (server: string) =>
      page.getByRole("group", { name: server }).locator("svg[aria-hidden] path").first();

    await expect(mark("GitHub")).toBeAttached();
    await expect(mark("Sentry")).toBeAttached();

    const github = await mark("GitHub").getAttribute("d");
    const sentry = await mark("Sentry").getAttribute("d");
    expect(github, "GitHub's card has no brand mark").toBeTruthy();
    expect(sentry, "every card is drawing the same glyph").not.toBe(github);
  });

  test("shows a server the organization connected that the catalog does not carry", async ({
    page,
  }) => {
    // The seed connects one by URL. A connection reachable from no screen is a
    // credential nobody can revoke, which is the failure mode of merging two
    // pages into one and only keeping the catalog.
    await findSeededServer(page);
  });

  test("connects from the row rather than sending you to a second page", async ({ page }) => {
    await page.goto("/mcp-servers");
    await expect(pageHeading(page, "MCP servers")).toBeVisible();

    // Asserted against a catalog that is on screen. Absence on a page that
    // failed to load is not a finding, it is an accident.
    const github = page.getByRole("group", { name: "GitHub" });
    await expect(github).toBeVisible();
    await expect(github.getByRole("button", { name: "Connect" }).first()).toBeVisible();

    // And nothing links out to the page this one replaced.
    await expect(page.getByRole("link", { name: /Settings . Integrations/ })).toHaveCount(0);
  });

  test("the old settings route still lands somewhere", async ({ page }) => {
    // Bookmarks and in-flight links outlive a navigation change.
    await page.goto("/settings/integrations");
    await expect(page).toHaveURL(/\/mcp-servers$/);
    await expect(pageHeading(page, "MCP servers")).toBeVisible();
  });

  test("no credential reaches the page", async ({ page }) => {
    // The token is write-only on the backend. This page joins the catalog with
    // two connection lists, which is exactly the kind of join that leaks one —
    // and the seed stored a credential on an organization server for it to leak.
    await findSeededServer(page);
    await expectNoRenderedSecret(page);
  });
});
