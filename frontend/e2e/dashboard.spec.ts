import { expect, test } from "./fixtures";

import type { UsageStats } from "../src/types/stats";
import { z } from "zod";

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

  test("keeps ranked bars separate from card footers at every card size", async ({ page }) => {
    const names = [SEEDED_AGENT_NAME, "Haiku", "Sonnet", "Glossary radar", "Opus"];
    const idle = [
      "Antoni Ghostwriter",
      "Client analysis",
      "Buying journey verifier",
      "vincent_v2",
      "oss-dashboard",
    ];
    const agentsResponse = await page.request.get("/api/agents");
    expect(agentsResponse.ok()).toBe(true);
    const catalog = z
      .object({ items: z.array(z.record(z.string(), z.unknown())) })
      .parse(await agentsResponse.json());
    const seeded = catalog.items.find((agent) => agent.name === SEEDED_AGENT_NAME);
    if (!seeded) throw new Error("The seeded agent is missing");
    const agents = [...names, ...idle].map((name, index) => ({
      ...seeded,
      id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      name,
      slug: `layout-agent-${index}`,
      status: "published",
      has_avatar: false,
    }));
    const usage: UsageStats = {
      from: "2026-10-04",
      to: "2026-11-03",
      scope: "org",
      total_runs: 331,
      previous_total_runs: 300,
      by_agent: agents
        .slice(0, 5)
        .map((agent, index) => ({ agent_id: agent.id, name: agent.name, runs: 104 - index * 15 })),
      cost: {
        period_usd: "71.93",
        previous_period_usd: "138.32",
        model_usd: "71.93",
        ingestion_usd: "0",
        eval_usd: "0",
        by_provider: [
          { provider: "anthropic", cost_usd: "51.14" },
          { provider: "openrouter", cost_usd: "17.11" },
          { provider: "openai", cost_usd: "3.68" },
        ],
      },
      by_day: null,
      timeline: null,
      by_surface: null,
      by_status: null,
      by_model: null,
      latency_ms: null,
      active_users: null,
      pending_approvals: null,
      agent_id: null,
      by_version: null,
      by_user: null,
      by_hour: null,
    };
    await page.route(/\/api\/agents(?:\?|$)/, (route) =>
      route.fulfill({ json: { items: agents, total: agents.length } }),
    );
    await page.route(/\/api\/stats\/usage(?:\?|$)/, (route) => route.fulfill({ json: usage }));
    await page.route("**/api/me/dashboard-layout", (route) =>
      route.fulfill({
        json: {
          entries: [
            { widget: "agents", span: "s6", rows: "r3" },
            { widget: "spend", span: "s6", rows: "r3" },
          ],
        },
      }),
    );
    await page.goto("/dashboard?view=org");
    const adoption = page.locator(".dash-widget").filter({
      has: page.getByRole("heading", { name: "Agents: adopted and forgotten", exact: true }),
    });
    const spend = page
      .locator(".dash-widget")
      .filter({ has: page.getByRole("heading", { name: "Spend", exact: true }) });
    await expect(
      adoption.getByRole("link", { name: SEEDED_AGENT_NAME, exact: true }),
    ).toBeVisible();
    await expect(spend.getByText("$51.14", { exact: true })).toBeVisible();
    const cards = [
      {
        card: adoption,
        last: adoption.getByRole("link", { name: "Opus", exact: true }),
        footer: adoption.getByText("Published but idle this period:", { exact: false }),
      },
      {
        card: spend,
        last: spend.getByText("$3.68", { exact: true }).locator(".."),
        footer: spend.getByText(/^This month so far:/),
      },
    ];
    for (const width of [390, 1440, 2560]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const height of [200, 296, 520]) {
        for (const { card, last, footer } of cards) {
          await card.evaluate((element, pixels) => {
            element.style.height = `${pixels}px`;
          }, height);
          await expect
            .poll(async () => {
              const end = await last.boundingBox();
              const after = await footer.boundingBox();
              return end && after ? after.y - end.y - end.height : -1;
            })
            .toBeGreaterThanOrEqual(8);
          await footer.scrollIntoViewIfNeeded();
          await expect(footer).toBeVisible();
          const bottomPadding = await footer.evaluate((element) => {
            const body = element.closest(".overflow-y-auto");
            if (!(body instanceof HTMLElement)) throw new Error("The card has no scroll body");
            body.scrollTop = body.scrollHeight;
            return body.getBoundingClientRect().bottom - element.getBoundingClientRect().bottom;
          });
          expect(bottomPadding).toBeGreaterThanOrEqual(16);
        }
      }
    }
  });

  test("waits for the complete opening while preserving the dashboard header", async ({ page }) => {
    for (const width of [1440, 390]) {
      let release: (() => void) | undefined;
      const pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      const startState = (url: URL) => url.pathname === "/api/me/onboarding";
      await page.route(startState, async (route) => {
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        const data: unknown = await response.json();
        if (!data || typeof data !== "object" || Array.isArray(data))
          throw new Error("Invalid start state");
        await pending;
        await route.fulfill({
          json: {
            ...data,
            dismissed: false,
            completed: false,
            has_activity: false,
            agents: [],
            has_result: false,
            latest_conversation_id: null,
            latest_completed_at: null,
          },
        });
      });
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/dashboard?view=me");
      const startPanel = page.getByRole("region", {
        name: "Start with something useful",
        exact: true,
      });
      const opening = page.getByRole("main").locator('[role="status"][aria-busy="true"]');
      await expect(opening).toHaveCount(1);
      await expect(opening).toBeVisible();
      await expect(startPanel).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Briefing", exact: true })).toHaveCount(0);
      await expect(page.getByText(/Your agents ran/)).toBeVisible();
      const briefing = page
        .locator(".dash-widget")
        .filter({ has: page.getByRole("heading", { name: "Briefing", exact: true }) });
      const period = page.getByRole("heading", { name: "Your period", exact: true });
      const heading = page.getByRole("heading", { level: 1 });
      const beforeHeading = await heading.boundingBox();
      release?.();
      await expect(opening).toHaveCount(0);
      await expect(
        startPanel.getByRole("link", { name: "Get started", exact: true }),
      ).toHaveAttribute("href", "/onboarding");
      const afterHeading = await heading.boundingBox();
      const afterBriefing = await briefing.boundingBox();
      const checklist = await startPanel.boundingBox();
      const afterPeriod = await period.boundingBox();
      if (!beforeHeading || !afterHeading || !afterBriefing || !checklist || !afterPeriod)
        throw new Error("Opening did not render");
      expect(Math.abs(afterHeading.y - beforeHeading.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(afterHeading.width - beforeHeading.width)).toBeLessThanOrEqual(1);
      if (width >= 1024) {
        expect(afterBriefing.x).toBeGreaterThanOrEqual(checklist.x + checklist.width);
        expect(Math.abs(afterBriefing.y - checklist.y)).toBeLessThanOrEqual(1);
      } else {
        expect(afterBriefing.y).toBeGreaterThanOrEqual(checklist.y + checklist.height);
      }
      expect(afterPeriod.y).toBeGreaterThanOrEqual(afterBriefing.y + afterBriefing.height);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      );
      await page.unroute(startState);
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
