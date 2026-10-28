import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BudgetHeadroomWidget } from "./budget-headroom";

const agent = (id: string, name: string, cap: number | null) => ({
  id,
  name,
  slug: name.toLowerCase(),
  budget_monthly_usd: cap,
});

vi.mock("@/hooks", () => ({
  useOrganizationList: () => ({
    data: [{ id: "o-1", monthly_budget_usd: "100" }],
    isLoading: false,
  }),
  useSpend: () => ({
    spend: {
      month_to_date_usd: "40",
      by_agent: [
        { agent_id: "a-near", cost_usd: "9" },
        { agent_id: "a-half", cost_usd: "5" },
        { agent_id: "a-low", cost_usd: "1" },
      ],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useAgents: () => ({
    agents: [
      agent("a-low", "Low", 50),
      agent("a-near", "Near", 10),
      agent("a-free", "Uncapped", null),
      agent("a-half", "Half", 10),
    ],
  }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "o-1" }),
}));

describe("the budget headroom card", () => {
  it("shows the agents closest to their cap, and how many more it left out", () => {
    render(
      <BudgetHeadroomWidget
        title="Budget headroom"
        hint=""
        period={{ preset: "30d", from: "2026-09-12", to: "2026-10-11" }}
      />,
    );

    expect(document.querySelectorAll("[data-agent-avatar]")).toHaveLength(2);
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("Near")).toBeInTheDocument();
    expect(screen.getByText("Half")).toBeInTheDocument();
    // Third closest, and the card holds two: counted, not drawn off its edge.
    expect(screen.queryByText("Low")).toBeNull();
    expect(screen.getByText("1 more agent with a cap")).toBeInTheDocument();
    expect(screen.queryByText("Uncapped")).toBeNull();
  });
});
