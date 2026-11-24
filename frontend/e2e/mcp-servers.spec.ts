import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_ORG_MCP_NAME, expectNoRenderedSecret, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * MCP servers — one catalog in the Connections page's MCP tab.
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

/** Servers every deployment ships. */
const CATALOG = ["GitHub", "PostgreSQL", "Notion", "Sentry"] as const;
type CatalogName = (typeof CATALOG)[number];

/** The visible descriptions of these specific curated MCP entries. */
const CATALOG_DESCRIPTIONS: Record<CatalogName, string> = {
  GitHub: "Read issues, pull requests and code across an organization's repositories.",
  PostgreSQL: "Query your own database over a Postgres MCP server you run. Not hosted by anybody.",
  Notion: "Search pages and databases in a Notion workspace.",
  Sentry: "Look up errors, issues and releases.",
};

/**
 * Managed apps and public-registry entries may share a curated server's name.
 * Match its visible description as well, so a different GitHub connector cannot
 * satisfy the assertion. The Registry badge still excludes unreviewed entries.
 */
function curatedServer(page: Page, name: CatalogName) {
  return page.getByRole("group", { name, exact: true }).filter({
    has: page.getByText(CATALOG_DESCRIPTIONS[name], { exact: true }),
    hasNot: page.getByText("Registry", { exact: true }),
  });
}

/** Legacy links reach Connections; its MCP tab holds the server catalog. */
async function openMcpServers(page: Page, path = "/mcp-servers") {
  await page.goto(path);
  await expect(page).toHaveURL(/\/connectors$/);
  await expect(pageHeading(page, "Connections")).toBeVisible();
  const tab = page.getByRole("tab", { name: "MCP servers", exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
}

/**
 * Bring the seeded custom server into view.
 *
 * The page is one grid over the whole catalog, fifty cards to a page, and custom
 * servers sort *last* - so a connection somebody made by URL is on page two and
 * `getByRole("group", ...)` finds nothing. Searching is what a person does, and it
 * is the only step these assertions were missing.
 */
async function findSeededServer(page: Page) {
  await openMcpServers(page);
  await page.getByRole("textbox", { name: "Search servers…" }).fill(SEEDED_ORG_MCP_NAME);
  const card = page.getByRole("group", { name: SEEDED_ORG_MCP_NAME });
  await expect(card).toBeVisible();
  return card;
}

test.describe("MCP servers", () => {
  test("lists every server the deployment curates, with what each needs", async ({ page }) => {
    await openMcpServers(page);

    for (const server of CATALOG) {
      await page.getByRole("textbox", { name: "Search servers…" }).fill(server);
      const card = curatedServer(page, server);
      await expect(card, `${server} should have one curated catalog entry`).toHaveCount(1);
      await expect(card, `${server} should be in the catalog`).toBeVisible();
      // Every card has the same foot whatever its state: where it stands, and
      // the verb that connects it. The category, the address and the auth it
      // needs are in the server's own dialog, one click away.
      await expect(
        card.getByRole("button", { name: "Connect", exact: true }),
        `${server} should offer to connect`,
      ).toBeVisible();
    }
  });

  test("says how many accounts each server holds, and opens them", async ({ page }) => {
    // The card used to carry a chip per connection, which made a server with
    // three accounts stand taller than its neighbours and the grid go ragged
    // (#1341). It carries two controls now whatever it holds: connect, and a
    // count that opens the accounts behind it. Who owns each one is inside,
    // where there is room to say it - and that distinction is not decoration,
    // because only the organization's can be bound to an agent.
    const card = await findSeededServer(page);
    // The count is a number beside a mark; the button's name says it in words.
    const manage = card.getByRole("button", { name: /^Manage \d+ connections? on/ });

    // The count is in the button's name; what it shows is the account's state.
    await expect(manage).toBeVisible();

    await manage.click();
    // By their headings: the dialog also says "Yours" in the caption under it,
    // and a substring match resolves to two elements and fails strict mode -
    // which would be a test asserting on prose rather than on the two owners.
    const accounts = page.getByRole("dialog");
    await expect(accounts.getByRole("heading", { name: "The organization's" })).toBeVisible();
    await expect(accounts.getByRole("heading", { name: "Yours" })).toBeVisible();
  });

  test("marks each card with the service's own logo", async ({ page }) => {
    // The reported regression, guarded against the real build: the catalog
    // rendered one generic icon on every row, which in a grid is the same as no
    // icons at all. Asserted as "two cards draw different glyphs" rather than on
    // a class or a file name — identical marks are the bug, whatever draws them.
    await openMcpServers(page);

    // A baked full-colour logo where the catalog has one, a brand glyph where
    // it does not: either way the mark is the first image on the card.
    const mark = (server: CatalogName) => curatedServer(page, server).locator("img, svg").first();

    await expect(mark("GitHub")).toBeAttached();
    await expect(mark("Sentry")).toBeAttached();

    const github = await mark("GitHub").evaluate((node) => node.outerHTML);
    const sentry = await mark("Sentry").evaluate((node) => node.outerHTML);
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
    await openMcpServers(page);

    // Asserted against a catalog that is on screen. Absence on a page that
    // failed to load is not a finding, it is an accident.
    const github = curatedServer(page, "GitHub");
    await expect(github).toBeVisible();
    await expect(github.getByRole("button", { name: "Connect", exact: true })).toBeVisible();

    // And nothing links out to the page this one replaced.
    await expect(page.getByRole("link", { name: /Settings . Integrations/ })).toHaveCount(0);
  });

  test("the old settings route still lands somewhere", async ({ page }) => {
    // Bookmarks and in-flight links outlive a navigation change.
    await openMcpServers(page, "/settings/integrations");
    await expect(curatedServer(page, "GitHub")).toBeVisible();
  });

  test("no credential reaches the page", async ({ page }) => {
    // The token is write-only on the backend. This page joins the catalog with
    // two connection lists, which is exactly the kind of join that leaks one —
    // and the seed stored a credential on an organization server for it to leak.
    await findSeededServer(page);
    await expectNoRenderedSecret(page);
  });
});
