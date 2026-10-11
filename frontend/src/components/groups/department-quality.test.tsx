import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DepartmentQuality } from "./department-quality";
import type { Group, GroupQualityDetail } from "@/types/groups";

const hooks = vi.hoisted(() => ({
  quality: undefined as GroupQualityDetail | undefined,
  isLoading: false,
  error: null as Error | null,
}));
vi.mock("@/hooks", () => ({
  useGroupQuality: () => hooks,
  useAgents: () => ({
    agents: [{ id: "a-pay", slug: "payables", has_avatar: false, name: "Payables" }],
  }),
}));

const GROUP: Group = {
  id: "g-fin",
  organization_id: "o-1",
  name: "Finance",
  description: null,
  icon: null,
  monthly_budget_usd: null,
  member_count: 3,
  created_at: "2026-09-01T00:00:00Z",
};

function detail(overrides: Partial<GroupQualityDetail> = {}): GroupQualityDetail {
  return {
    group_id: "g-fin",
    from_date: "2026-09-12",
    to_date: "2026-10-11",
    likes: 3,
    dislikes: 1,
    top_agents: [{ agent_id: "a-pay", name: "Payables", run_count: 7 }],
    down_rated: [
      {
        rated_at: "2026-10-10T09:00:00Z",
        comment: "Wrong VAT rate",
        run_id: "r-1",
        agent_id: "a-pay",
        agent_name: "Payables",
      },
      {
        rated_at: "2026-10-09T09:00:00Z",
        comment: null,
        run_id: null,
        agent_id: null,
        agent_name: null,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  hooks.quality = undefined;
  hooks.isLoading = false;
  hooks.error = null;
});

describe("a department's answer quality (#2101)", () => {
  it("shows the helpful share, the busiest agents and the answers rated not helpful", () => {
    hooks.quality = detail();
    render(<DepartmentQuality orgId="o-1" group={GROUP} />);

    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("helpful - 3 of 4 ratings")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Payables/ })).toHaveAttribute("href", "/agents/a-pay");
    expect(screen.getByText("7 runs")).toBeInTheDocument();
    expect(screen.getByText("“Wrong VAT rate”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run" })).toHaveAttribute("href", "/runs?run=r-1");
    // An answer from before messages named their run: no agent, no link, no words.
    expect(screen.getByText("No comment left")).toBeInTheDocument();
    expect(screen.getByText(/^An agent ·/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Run" })).toHaveLength(1);
  });

  it("reads agents ran but unrated as no ratings, not as nothing", () => {
    hooks.quality = detail({ likes: 0, dislikes: 0, down_rated: [] });
    render(<DepartmentQuality orgId="o-1" group={GROUP} />);

    expect(screen.getByText("No ratings in the last 30 days")).toBeInTheDocument();
    expect(screen.getByText("7 runs")).toBeInTheDocument();
  });

  it("says nobody has rated yet when nothing ran or was rated", () => {
    hooks.quality = detail({ likes: 0, dislikes: 0, top_agents: [], down_rated: [] });
    render(<DepartmentQuality orgId="o-1" group={GROUP} />);

    expect(screen.getByText("Nobody here has rated an answer yet")).toBeInTheDocument();
  });

  it("waits while loading and says what failed", () => {
    hooks.isLoading = true;
    const { unmount } = render(<DepartmentQuality orgId="o-1" group={GROUP} />);
    expect(screen.queryByText("75%")).not.toBeInTheDocument();
    unmount();

    hooks.isLoading = false;
    hooks.error = new Error("The server is down");
    render(<DepartmentQuality orgId="o-1" group={GROUP} />);
    expect(screen.getByText("The server is down")).toBeInTheDocument();
  });
});
