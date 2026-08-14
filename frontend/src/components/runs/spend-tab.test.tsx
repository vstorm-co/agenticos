import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpendTab } from "./spend-tab";
import type { Period } from "@/lib/dashboard/period";
import { apiClient } from "@/lib/api-client";
import type { CostByAgent, CostSummary } from "@/types/runs";

/**
 * The Spend tab with money in it.
 *
 * Every other test on this page serves an empty `/spend`, which exercises none of
 * the rows and is exactly the shape a reader cannot check against an invoice. The
 * cases here are the ones that decide whether the breakdown *adds up*: a vendor
 * recorded before the column existed and a key since deleted are kept and muted
 * rather than dropped, because the money was spent either way and a breakdown
 * that quietly stops summing to the total is worse than one with an honest "not
 * recorded" line in it.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn() } };
});

const PERIOD: Period = { preset: "30d", from: "2026-07-16", to: "2026-08-14" };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function serve(spend: Partial<CostSummary>) {
  vi.mocked(apiClient.get).mockResolvedValue({
    period_days: 30,
    from_date: "2026-07-08T00:00:00Z",
    to_date: null,
    month_to_date_usd: "0.00",
    partial_run_count: 0,
    by_agent: [],
    by_provider: [],
    by_key: [],
    ...spend,
  });
}

/** The row holding `label`, so a figure is read against its own subject. */
function row(label: string): HTMLElement {
  const found = screen.getByText(label).closest<HTMLElement>("div.rounded-md");
  if (found === null) throw new Error(`no spend row for ${label}`);
  return found;
}

beforeEach(() => vi.mocked(apiClient.get).mockReset());

describe("the spend breakdown by vendor and by key", () => {
  it("names each vendor with what it was paid", async () => {
    serve({
      by_provider: [
        { provider: "openai", cost_usd: "1.5000", run_count: 12 },
        { provider: "anthropic", cost_usd: "0.2500", run_count: 3 },
      ],
    });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("openai")).toBeVisible();
    expect(row("openai")).toHaveTextContent("$1.5000");
    expect(row("openai")).toHaveTextContent("12 runs");
    expect(row("anthropic")).toHaveTextContent("$0.2500");
  });

  it("keeps spend from before the vendor was recorded, and says so", async () => {
    // Dropping the row would make the column stop summing to the total above it.
    // Folding it into a named vendor would be worse: an invoice checked against
    // it would disagree, and nothing on screen would say why.
    serve({ by_provider: [{ provider: null, cost_usd: "0.4000", run_count: 2 }] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Not recorded")).toBeVisible();
    expect(row("Not recorded")).toHaveTextContent("$0.4000");
  });

  it("names the key each run was billed through", async () => {
    // How a leaked or misused credential is found: not which vendor was paid,
    // but which key it was paid with.
    serve({
      by_key: [
        { secret_id: "sec-1", label: "OpenAI · production", cost_usd: "2.0000", run_count: 8 },
      ],
    });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("OpenAI · production")).toBeVisible();
    expect(row("OpenAI · production")).toHaveTextContent("$2.0000");
  });

  it("still accounts for a key that has since been deleted", async () => {
    // Rotating a key must not silently take its spend out of the history.
    serve({ by_key: [{ secret_id: null, label: null, cost_usd: "0.7500", run_count: 4 }] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Deleted key")).toBeVisible();
    expect(row("Deleted key")).toHaveTextContent("$0.7500");
  });

  it("says nothing spent when a breakdown genuinely has no rows", async () => {
    serve({});

    render(<SpendTab period={PERIOD} />, { wrapper });

    // Three: one per vendor-and-key breakdown, and one for the per-agent card,
    // which has a message of its own with the same wording. And it is the empty
    // sentence rather than the failed one - `tab-failures.integration.test.tsx`
    // covers the difference between them.
    expect(await screen.findByText("By provider")).toBeVisible();
    expect(screen.getAllByText("Nothing spent yet.")).toHaveLength(3);
  });
});

describe("the unpriced-runs caveat over the whole window", () => {
  it("says how many of the window's runs could not be priced", async () => {
    // The one caveat that governs every figure below: the breakdowns are a floor
    // by exactly this many, and saying so once at the top is what stops a reader
    // treating the totals as exact.
    serve({ partial_run_count: 3, month_to_date_usd: "31.20" });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText(/3 runs in this window could not be priced/)).toBeVisible();
  });

  it("says nothing when every run in the window was priced", async () => {
    serve({ partial_run_count: 0 });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("By provider")).toBeVisible();
    expect(screen.queryByText(/could not be priced/)).toBeNull();
  });
});

function agentRow(overrides: Partial<CostByAgent> = {}): CostByAgent {
  return {
    agent_id: "agent-1",
    agent_name: "Billing clerk",
    // Null on every row this endpoint returns. It is populated only on the usage
    // email's per-model rows, which is the whole reason the tab must not read it.
    model_label: null,
    cost_usd: "1.2500",
    run_count: 5,
    partial_run_count: 0,
    month_to_date_usd: "1.2500",
    monthly_cap_usd: null,
    ...overrides,
  };
}

describe("the spend breakdown by agent", () => {
  it("names the agent, which is what the row is", async () => {
    // It rendered `model_label` here, which this endpoint sends as null on every
    // row - so the column read "-" all the way down. Before the backend grouped
    // by agent it read model labels, and one agent run on two models was two
    // rows with no agent named on either.
    serve({ by_agent: [agentRow()] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Billing clerk")).toBeVisible();
    expect(row("Billing clerk")).toHaveTextContent("5 runs");
    expect(row("Billing clerk")).toHaveTextContent("$1.2500");
  });

  it("groups one agent into one row whatever it ran on", async () => {
    serve({ by_agent: [agentRow(), agentRow({ agent_id: "agent-2", agent_name: "Researcher" })] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Billing clerk")).toBeVisible();
    expect(screen.getByText("Researcher")).toBeVisible();
    expect(screen.getAllByText("5 runs")).toHaveLength(2);
  });

  it("says how many of an agent's runs could not be priced", async () => {
    // The cost is a floor by exactly that many. "3 unpriced" is actionable where
    // a bare figure a reader has to take on trust is not.
    serve({ by_agent: [agentRow({ run_count: 40, partial_run_count: 3 })] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("3 unpriced")).toBeVisible();
  });

  it("says nothing about pricing when every run was priced", async () => {
    serve({ by_agent: [agentRow({ partial_run_count: 0 })] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Billing clerk")).toBeVisible();
    expect(screen.queryByText(/unpriced/)).toBeNull();
  });

  it("still accounts for an agent that has since been deleted", async () => {
    serve({ by_agent: [agentRow({ agent_name: null })] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Deleted agent")).toBeVisible();
  });

  it("says nothing spent yet when no agent has cost anything", async () => {
    serve({ by_agent: [] });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Spend by agent")).toBeVisible();
    expect(screen.getByText("Last 30 days.")).toBeVisible();
  });
});

describe("the window these figures cover", () => {
  it("names an explicit range rather than the default number of days", async () => {
    // `GET /spend` answers `period_days: null` whenever `from` was sent, because
    // a count of days beside a range is a second answer to a settled question.
    // Read through a `?? 30` it rendered "Last 30 days." over July, which is the
    // reassuring wrong answer: nothing on screen looks unusual.
    serve({
      period_days: null,
      from_date: "2026-07-01T00:00:00Z",
      to_date: "2026-07-31T00:00:00Z",
    });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Jul 1, 2026 to Jul 31, 2026.")).toBeVisible();
    expect(screen.queryByText(/Last 30 days/)).toBeNull();
  });

  it("says the range runs up to now when it has no end", async () => {
    // A word, not a date. `to` is optional on the route and defaults to now, and
    // putting that through the date formatter writes a bare dash where the end
    // of the window should be.
    serve({ period_days: null, from_date: "2026-07-01T00:00:00Z", to_date: null });

    render(<SpendTab period={PERIOD} />, { wrapper });

    expect(await screen.findByText("Jul 1, 2026 to now.")).toBeVisible();
  });
});
