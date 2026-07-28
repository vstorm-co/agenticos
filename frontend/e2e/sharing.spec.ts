import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  DRAFT_AGENT_NAME,
  OWNER_EMAIL,
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

/** Open the Sharing tab of an agent and wait for it to have loaded. */
async function openSharing(page: Page, agent: string): Promise<Locator> {
  await openAgent(page, agent);
  await page.getByRole("tab", { name: "Sharing" }).click();

  const panel = page.getByRole("tabpanel");
  // The panel renders a spinner until both the sharing state and the member
  // list arrive, and the owner's email comes from the second — so this is the
  // point at which anything below is reading real data rather than a default.
  await expect(panel.getByText(`Owned by ${OWNER_EMAIL}`)).toBeVisible();
  return panel;
}

test.describe("Sharing", () => {
  test("shares an agent, changes the level, then revokes it", async ({ page }) => {
    const panel = await openSharing(page, SEEDED_AGENT_NAME);

    await panel.getByLabel("Add someone").click();
    // The picker offers members of this organization and nobody else — the
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
    await page.getByRole("tab", { name: "Sharing" }).click();
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveText("Can use");

    await panel.getByRole("button", { name: `Remove ${COLLEAGUE_EMAIL}` }).click();
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveCount(0);

    await page.reload();
    await page.getByRole("tab", { name: "Sharing" }).click();
    await expect(panel.getByLabel(`Access for ${COLLEAGUE_EMAIL}`)).toHaveCount(0);
    await expect(panel.getByText("Not shared with anyone yet.")).toBeVisible();
  });

  test("says who each visibility reaches before it is chosen", async ({ page }) => {
    const panel = await openSharing(page, SEEDED_AGENT_NAME);

    // "Private", "Team" and "Organization" mean nothing on their own — the
    // sentence under each is the only place the blast radius is stated.
    await expect(panel.getByRole("radio", { name: "Private" })).toBeVisible();
    await expect(
      panel.getByText("Everyone in the organization who can view agents at all."),
    ).toBeVisible();

    // Which one is selected is the agent's stored visibility, not a default the
    // component picked: bootstrap publishes this agent private.
    await expect(panel.getByRole("radio", { name: "Private" })).toBeChecked();
  });

  test("a change of visibility is stored, not just shown", async ({ page }) => {
    const panel = await openSharing(page, DRAFT_AGENT_NAME);

    // Clicked rather than `check()`ed: the radio is controlled by the stored
    // visibility, so it stays where it was until the write comes back. `check()`
    // asserts the box flipped the instant it was clicked, which here would be
    // asserting that the UI lied optimistically.
    await panel.getByRole("radio", { name: "Team" }).click();
    await expect(panel.getByRole("radio", { name: "Team" })).toBeChecked();

    await page.reload();
    await page.getByRole("tab", { name: "Sharing" }).click();
    await expect(panel.getByRole("radio", { name: "Team" })).toBeChecked();

    // Put it back: the draft is a shared fixture, and a test that leaves the
    // database somewhere else than it found it is a test that only works once.
    await panel.getByRole("radio", { name: "Private" }).click();
    await expect(panel.getByRole("radio", { name: "Private" })).toBeChecked();
  });
});
