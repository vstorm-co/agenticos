import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_AGENT_NAME, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * The role-aware dashboard, as the seeded owner sees it.
 *
 * Deliberately not asserted: how many runs there are, or that there are none.
 * The journey spec creates a run and the suite may order itself either way -
 * and a lived-in dev database has real history. What is stable is the page's
 * core claim: every card resolves to data or to its empty state, and none of
 * them dresses a failed request as "no rows".
 */
test.describe("Dashboard", () => {
  test("shows the owner their sections, with data where the seed has any", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(pageHeading(page, "Dashboard")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Usage & cost" })).toBeVisible();

    // Data-borne: the seeded agent's name arrived from GET /agents.
    await expect(page.getByRole("main").getByText(SEEDED_AGENT_NAME).first()).toBeVisible();
    // The approvals queue resolved and is empty - which the card says proudly.
    await expect(page.getByText("Nothing waiting")).toBeVisible();
  });

  test("every card resolves, and none shows the error body", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(pageHeading(page, "Dashboard")).toBeVisible();

    // Settled: every widget skeleton is gone (they all carry role=status).
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
      timeout: 20_000,
    });
    // Not one card shows the error body. A 502 rendering as an empty state is
    // the silent failure this page was designed against.
    await expect(page.getByText("Couldn't load this")).toHaveCount(0);
  });

  test("switching the period writes the URL, so the view travels", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(pageHeading(page, "Dashboard")).toBeVisible();

    await page.getByRole("button", { name: "Last 7 days" }).click();

    await expect(page).toHaveURL(/period=7d/);
  });
});
