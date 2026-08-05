import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  SEEDED_AGENT_HANDLE,
  SEEDED_AGENT_NAME,
  SEEDED_KB_NAME,
  FAKE_KEY_LABEL,
  SEEDED_SKILL_NAME,
  agentCard,
  gotoRoleMatrix,
  openAgent,
  pageHeading,
  skillCard,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Every dashboard page gets past its loading state, says what it is, and shows
 * something that could only have come from the backend.
 *
 * The last part is what makes this more than a smoke test. These pages are
 * client components that fan out to several queries each, and every one of them
 * renders its empty state when a query fails — so a page that named itself and
 * listed nothing used to pass here while every request under it 502'd. Each
 * entry therefore carries a `proof`: one locator that is on screen only if the
 * data behind the page arrived.
 */

const DASHBOARD_PAGES: {
  path: string;
  heading: string | RegExp;
  proof: (page: Page) => Locator;
}[] = [
  {
    path: "/agents",
    heading: "Agents",
    proof: (page) => agentCard(page, SEEDED_AGENT_HANDLE),
  },
  {
    path: "/skills",
    heading: "Skills",
    proof: (page) => skillCard(page, SEEDED_SKILL_NAME),
  },
  {
    // Activity has no seeded row — a run needs a real provider key. Its queries
    // are asserted directly in `activity.spec.ts`; here the proof is the one
    // control on the page that only renders once the approvals query resolved.
    path: "/runs",
    heading: "Activity",
    proof: (page) => page.getByRole("heading", { name: "Nothing waiting" }),
  },
  {
    path: "/rag",
    heading: "Knowledge bases",
    proof: (page) => page.getByText(SEEDED_KB_NAME, { exact: true }).first(),
  },
  {
    path: "/orgs",
    heading: "Organizations",
    proof: (page) => page.getByRole("heading", { level: 2, name: "Personal" }),
  },
  {
    path: "/vault",
    heading: "Vault",
    // A stored key, not a model profile. The Vault is secrets now - model
    // profiles moved to the Builder and the chat's model picker - so
    // `SEEDED_MODEL_LABEL` was proof of something this page no longer shows.
    proof: (page) => page.getByRole("main").getByText(FAKE_KEY_LABEL).first(),
  },
];

test.describe("Dashboard navigation", () => {
  /**
   * The dashboard is the one page in the list above with no `proof` to give:
   * it is being rebuilt and asks the backend for nothing at all. It stays
   * covered because it is where the sidebar and the skip link live, but what
   * is asserted here is only that it says what it is.
   */
  test("/dashboard says it is under construction", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(pageHeading(page, "Dashboard")).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Under construction" })).toBeVisible();
  });

  for (const { path, heading, proof } of DASHBOARD_PAGES) {
    test(`${path} loads, names itself and has its data`, async ({ page }) => {
      await page.goto(path);

      await expect(pageHeading(page, heading)).toBeVisible();

      // A page that renders a heading but drops its main landmark is broken for
      // keyboard and screen-reader users, and the layout's skip link points at
      // nothing.
      await expect(page.getByRole("main")).toBeVisible();

      await expect(proof(page), `${path} rendered its shell but not its data`).toBeVisible();
    });
  }

  test("the agent builder names the agent it is building", async ({ page }) => {
    await openAgent(page, SEEDED_AGENT_NAME);

    // The builder's title is the agent plus its publish state — the one piece of
    // context that decides what every tab below it is allowed to do.
    await expect(pageHeading(page)).toContainText("published");
    await expect(page.getByRole("tab", { name: "Build" })).toBeVisible();
  });

  /**
   * AI providers and the MCP catalog were under `/settings/` while also being
   * primary sidebar destinations, so a page lived in two navigations at once.
   * They moved to the top level; a bookmark or an older link still has to work.
   *
   * The provider page then became the vault, because provider keys were never
   * the whole of what it held. Both of its older spellings are here: a URL
   * someone bookmarked has no way of knowing which rename it predates.
   */
  const MOVED_ROUTES: readonly (readonly [string, string])[] = [
    ["/settings/providers", "/vault"],
    ["/providers", "/vault"],
    ["/settings/mcp-servers", "/mcp-servers"],
  ];

  for (const [from, to] of MOVED_ROUTES) {
    test(`${from} still reaches ${to}`, async ({ page }) => {
      await page.goto(from);

      await expect(page).toHaveURL(new RegExp(`${to}$`));
      await expect(page.getByRole("main")).toBeVisible();
    });
  }

  test("the role matrix is reachable from an organization", async ({ page }) => {
    await gotoRoleMatrix(page);

    await expect(page.getByText("Permission matrix")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Permission" })).toBeVisible();

    // The matrix is served by the backend, so a row from the real catalog is
    // what separates "the table rendered" from "the table rendered empty".
    await expect(page.getByRole("cell", { name: /^agents:edit/ })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "owner" })).toBeVisible();

    // The scopes are the catalog's, not the component's: `member` may edit what
    // it owns and nothing wider. A table rendered from an empty response has the
    // headers and none of this.
    await expect(page.getByRole("row", { name: /^agents:edit/ })).toContainText("own");
  });
});
