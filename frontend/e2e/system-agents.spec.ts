import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  CAPABILITY_WITH_TOOLS,
  SEEDED_JUDGE_KEY,
  SEEDED_JUDGE_NAME,
  openBuilderTab,
  pageHeading,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * A system agent's page, on the judge the backend seeds into every organization.
 *
 * It keeps an ordinary agent's tabs, fewer of them: its Toolbox is the same
 * workbench, handed only what a system agent may bind, and its knowledge search
 * picks no collection - the platform hands each run the knowledge bases it is
 * about, so the panel sets how many steps a search takes instead.
 *
 * The judge is found through the API by its key, so a missing seed fails on the
 * lookup rather than on a page that rendered nothing.
 */

/** The organization the console acts in, which the API reads from a header. */
async function activeOrganization(page: Page): Promise<string> {
  const read = () =>
    page.evaluate(() => {
      const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
      if (typeof value !== "object" || value === null || !("state" in value)) return null;
      const state = value.state as { activeOrgId?: unknown };
      return typeof state.activeOrgId === "string" ? state.activeOrgId : null;
    });
  await expect.poll(read).toBeTruthy();
  return (await read()) ?? "";
}

test("a system agent's Toolbox offers its knowledge search, without collections", async ({
  page,
}) => {
  await page.goto("/agents");
  const headers = { "X-Organization-Id": await activeOrganization(page) };
  const response = await page.request.get("/api/agents?kind=judge", { headers });
  expect(response.ok(), `/api/agents?kind=judge answered ${response.status()}`).toBe(true);
  const { items } = (await response.json()) as {
    items: { id: string; system_key: string | null }[];
  };
  const judge = items.find((agent) => agent.system_key === SEEDED_JUDGE_KEY);
  expect(judge, "the organization lists no seeded eval judge").toBeDefined();

  await page.goto(`/agents/${judge!.id}`);
  await expect(pageHeading(page)).toContainText(SEEDED_JUDGE_NAME);
  await expect(page.getByRole("tab", { name: "MCP servers", exact: true })).toHaveCount(0);
  await openBuilderTab(page, "Toolbox");

  await expect(
    page.getByRole("switch", { name: `Give this agent ${CAPABILITY_WITH_TOOLS}`, exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: `${CAPABILITY_WITH_TOOLS} settings`, exact: true })
    .click();
  const panel = page.getByRole("group", { name: CAPABILITY_WITH_TOOLS, exact: true });
  await expect(panel.getByRole("tab", { name: "Knowledge base", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(panel.getByRole("spinbutton", { name: "Max steps" })).toBeVisible();
  await expect(panel.getByRole("tab", { name: "Collections", exact: true })).toHaveCount(0);
});
