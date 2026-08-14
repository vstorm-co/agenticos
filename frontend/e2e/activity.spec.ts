import { expect, test } from "./fixtures";

import { AUTH_STATE, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Activity is the page an operator opens when something has gone wrong or a
 * bill has arrived. Every one of its three views has to be reachable and none
 * of them may render as an empty rectangle — "nothing here" and "this failed to
 * load" look identical when a page says nothing at all.
 *
 * This is the one page in the suite with no seeded row to assert on. A run
 * costs a model call, and a model call needs a real provider key: without one
 * the backend refuses before it writes a run, so there is nothing to list. The
 * journey that does have a key asserts the run *and* its cost end to end
 * (`journey.spec.ts`); what is left here has to prove the queries resolved
 * some other way, and the only honest one is the response itself. Hence the
 * explicit status assertions below, on top of the suite-wide 5xx guard.
 */

/** The three requests this page fans out to, and what each one feeds. */
const QUERIES = ["/api/runs", "/api/approvals", "/api/spend"];

test.describe("Activity", () => {
  test("loads spend, runs and approvals, rather than defaulting to zero", async ({ page }) => {
    // Every tile on this page renders "0" or "$0.00" from a failed query just as
    // readily as from an empty organization, so the numbers prove nothing on
    // their own. What distinguishes the two is whether the request answered.
    const answered = QUERIES.map((path) =>
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === path && response.request().method() === "GET",
      ),
    );

    await page.goto("/runs");
    await expect(pageHeading(page, "Activity")).toBeVisible();

    for (const [index, pending] of answered.entries()) {
      const response = await pending;
      expect(response.status(), `${QUERIES[index]} did not answer`).toBe(200);
    }

    // The spend figure's caption, not its "Spend" label - the tab strip says
    // "Spend" too, and an exact-text locator would match both (#760 renamed the
    // figure from "Spend this month" to the page's shared window).
    await expect(
      page.getByText("Over the window above, so the two figures agree.", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Waiting on a person", { exact: true })).toBeVisible();
  });

  test("offers approvals, runs and spend", async ({ page }) => {
    await page.goto("/runs");
    await expect(pageHeading(page, "Activity")).toBeVisible();

    await expect(page.getByRole("tab", { name: /^Approvals/ })).toBeVisible();

    await page.getByRole("tab", { name: "Runs", exact: true }).click();
    await expect(page.getByText("Run history")).toBeVisible();

    await page.getByRole("tab", { name: "Spend", exact: true }).click();
    // The facet table's own title - "Spend by agent" died with the tile cards.
    await expect(page.getByText("Where the money went")).toBeVisible();
  });

  test("an empty approval queue says so", async ({ page }) => {
    await page.goto("/runs");
    await expect(pageHeading(page, "Activity")).toBeVisible();

    // The page opens on Runs now; the queue is one tab over.
    const approvals = page.getByRole("tab", { name: /^Approvals/ });
    await approvals.click();
    await expect(page.getByText("Waiting for a decision")).toBeVisible();

    // The tab carries a count badge only when something is queued, so its label
    // is the cheapest read of whether this environment can prove the empty case.
    const label = (await approvals.innerText()).trim();
    if (label !== "Approvals") {
      test.skip(true, `${label.replace(/\s+/g, " ")} — this environment has a non-empty queue`);
    }

    // An operator seeing a blank panel cannot tell "no agent needed you" from
    // "the approvals request failed". The empty state has to state which.
    const panel = page.getByRole("tabpanel");
    await expect(panel.getByRole("heading", { name: "Nothing waiting" })).toBeVisible();
    await expect(panel.getByText("Agents are running without needing you.")).toBeVisible();
  });
});
