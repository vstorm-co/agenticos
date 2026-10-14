import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  DRAFT_AGENT_NAME,
  SEEDED_AGENT_NAME,
  openAgent,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Sharing one agent with one colleague.
 *
 * The whole point of a grant is that it lifts one person's access to one row
 * without promoting them anywhere else, so the round trip is what matters:
 * share, change the level, revoke. Each step has to survive a reload — a panel
 * that only looks right until the next fetch is a panel that never wrote
 * anything.
 *
 * Bootstrap leaves a single-member organization, in which a grant has nobody to
 * be granted to and this spec could only ever skip itself. `seed.setup.ts`
 * invites a second member so it does not have to.
 *
 * The two tests that write use different agents on purpose: sharing edits the
 * seeded one, visibility edits the draft. Running them against the same row
 * would make them pass or fail on the order the workers happened to pick.
 */

/**
 * Open the panel that shares an agent, and wait for it to have loaded.
 *
 * Under Availability now rather than a tab of its own: who may reach this agent
 * is the same question as which channels it is exposed on, and the answer was
 * split across two tabs.
 */
async function openSharing(page: Page, agent: string): Promise<Locator> {
  await openAgent(page, agent);
  return openShareDialog(page);
}

/** The Share dialog off the agent header, beside Publish, once it holds real data. */
async function openShareDialog(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Share", exact: true }).click();

  const panel = page.getByRole("dialog");
  // The panel renders a spinner until both the sharing state and the member
  // list arrive, and the owner's row is built from the second - so this is the
  // point at which anything below is reading real data rather than a default.
  await expect(panel.getByText("Owner", { exact: true })).toBeVisible();
  return panel;
}

test.describe("Sharing", () => {
  test("shares an agent, changes the level, then revokes it", async ({ page }) => {
    const panel = await openSharing(page, SEEDED_AGENT_NAME);

    await panel.getByLabel("Add a person or group").click();
    // The picker offers members and groups of this organization and nobody else — the
    // owner is filtered out because they already have access, which leaves
    // exactly the colleague the setup invited.
    await page.getByRole("option", { name: COLLEAGUE_EMAIL }).click();
    await panel.getByRole("button", { name: "Share" }).click();

    const level = panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`);
    await expect(level).toBeVisible();
    await expect(level).toHaveText("Can view");

    // Levels are a ladder, not a flag: raising one is an upsert of the same
    // grant, and the panel has to show the level that was actually stored.
    await level.click();
    await page.getByRole("option", { name: "Can use" }).click();
    await expect(level).toHaveText("Can use");

    await page.reload();
    await openShareDialog(page);
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveText("Can use");

    await panel.getByRole("button", { name: `Remove ${COLLEAGUE_EMAIL}` }).click();
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveCount(0);

    await page.reload();
    await openShareDialog(page);
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveCount(0);
    await expect(panel.getByText("Not shared with anyone yet.")).toBeVisible();
  });

  test("says who the general access reaches", async ({ page }) => {
    const panel = await openSharing(page, SEEDED_AGENT_NAME);

    // "Everyone in the organization" means nothing on its own - the sentence
    // under it is the only place the blast radius is stated. Which one shows is
    // the agent's stored visibility: bootstrap publishes this one to the
    // organization, because it is the agent that explains the platform.
    const access = panel.getByRole("combobox", { name: "General access" });
    await expect(access).toHaveText("Everyone in the organization");
    await expect(
      panel.getByText("Everyone in the organization who can view agents at all."),
    ).toBeVisible();
  });

  test("a change of visibility is stored, not just shown", async ({ page }) => {
    const panel = await openSharing(page, DRAFT_AGENT_NAME);
    const access = panel.getByRole("combobox", { name: "General access" });

    await access.click();
    await page.getByRole("option", { name: "Everyone in the organization" }).click();
    await expect(access).toHaveText("Everyone in the organization");

    await page.reload();
    const reopened = await openShareDialog(page);
    await expect(reopened.getByRole("combobox", { name: "General access" })).toHaveText(
      "Everyone in the organization",
    );

    // Put it back: the draft is a shared fixture, and a test that leaves the
    // database somewhere else than it found it is a test that only works once.
    await reopened.getByRole("combobox", { name: "General access" }).click();
    await page.getByRole("option", { name: "Only people with access" }).click();
    await expect(reopened.getByRole("combobox", { name: "General access" })).toHaveText(
      "Only people with access",
    );
  });
});
