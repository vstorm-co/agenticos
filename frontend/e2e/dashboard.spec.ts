import { expect, test } from "./fixtures";

import { AUTH_STATE, DASHBOARD_GREETING, SEEDED_AGENT_NAME, pageHeading } from "./helpers";

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
  test("keeps the greeting summary below its title at wide and narrow widths", async ({ page }) => {
    await page.goto("/dashboard?view=me");
    const title = pageHeading(page, DASHBOARD_GREETING);
    const summary = page.getByText(/Your agents ran/);
    await expect(title).toBeVisible();
    await expect(summary).toBeVisible();
    for (const width of [2560, 1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await expect
        .poll(async () => {
          const headingBox = await title.boundingBox();
          const summaryBox = await summary.boundingBox();
          return headingBox && summaryBox ? summaryBox.y - headingBox.y - headingBox.height : -1;
        })
        .toBeGreaterThanOrEqual(0);
    }
  });

  test("sizes summary columns to the card rather than the screen", async ({ page }) => {
    await page.route("**/api/me/dashboard-layout", (route) =>
      route.fulfill({
        json: {
          entries: [
            { widget: "my-summary", span: "s6", rows: "r3" },
            { widget: "shared-with-you", span: "s6", rows: "r3" },
          ],
        },
      }),
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/dashboard?view=org");
    const card = page
      .locator(".dash-widget")
      .filter({ has: page.getByRole("heading", { name: "Your period", exact: true }) });
    const figures = card.locator("div.grid").first();
    await expect(figures).toBeVisible();
    const columnCount = () =>
      figures.evaluate(
        (element) => getComputedStyle(element).gridTemplateColumns.split(/\s+/).length,
      );
    await expect.poll(columnCount).toBe(2);
    await page.setViewportSize({ width: 2560, height: 1000 });
    await expect.poll(columnCount).toBe(4);
  });

  test("keeps the opening in place while checklist data arrives late", async ({ page }) => {
    for (const width of [1440, 390]) {
      let release: (() => void) | undefined;
      const pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      const agents = (url: URL) => url.pathname === "/api/agents";
      await page.route(agents, async (route) => {
        await pending;
        await route.fulfill({ json: { items: [], total: 0 } });
      });
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/dashboard?view=me");
      const checklist = page.getByRole("status", { name: "Loading", exact: true }).filter({
        has: page.getByRole("heading", { name: "Get started", exact: true }),
      });
      await expect(checklist).toBeVisible();
      await expect(page.getByText(/Your agents ran/)).toBeVisible();
      const briefing = page
        .locator(".dash-widget")
        .filter({ has: page.getByRole("heading", { name: "Briefing", exact: true }) });
      const period = page.getByRole("heading", { name: "Your period", exact: true });
      const beforeBriefing = await briefing.boundingBox();
      const beforePeriod = await period.boundingBox();
      release?.();
      await expect(checklist).toHaveCount(0);
      await expect(page.getByRole("progressbar")).toBeVisible();
      const afterBriefing = await briefing.boundingBox();
      const afterPeriod = await period.boundingBox();
      if (!beforeBriefing || !afterBriefing || !beforePeriod || !afterPeriod)
        throw new Error("Opening did not render");
      expect(Math.abs(afterBriefing.x - beforeBriefing.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(afterBriefing.width - beforeBriefing.width)).toBeLessThanOrEqual(1);
      expect(Math.abs(afterPeriod.y - beforePeriod.y)).toBeLessThanOrEqual(1);
      await page.unroute(agents);
    }
  });

  test("shows the owner their sections, with data where the seed has any", async ({ page }) => {
    // The sections are the organization's view; everybody opens on their own.
    await page.goto("/dashboard?view=org");

    await expect(pageHeading(page, "Dashboard")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Usage & cost" })).toBeVisible();

    // Data-borne: the seeded agent's name arrived from GET /agents.
    await expect(page.getByRole("main").getByText(SEEDED_AGENT_NAME).first()).toBeVisible();
    // The approvals queue resolved and is empty - which the card says proudly.
    await expect(page.getByText("Nothing waiting")).toBeVisible();
  });

  test("every card resolves, and none shows the error body", async ({ page }) => {
    // The view everybody opens on, their own.
    await page.goto("/dashboard");
    await expect(pageHeading(page, DASHBOARD_GREETING)).toBeVisible();

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
    await expect(pageHeading(page, DASHBOARD_GREETING)).toBeVisible();

    await page.getByRole("button", { name: "Period", exact: true }).click();
    await page.getByRole("menuitemradio", { name: "Last 7 days" }).click();

    await expect(page).toHaveURL(/period=7d/);
  });
});
