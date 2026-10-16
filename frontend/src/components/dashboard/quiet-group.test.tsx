import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Group } from "@/types/groups";

import { QuietGroup } from "./quiet-group";

const data = vi.hoisted(() => ({ usage: null as { total_runs: number } | null }));

vi.mock("@/hooks", () => ({
  useUsageStats: () => ({ usage: data.usage }),
}));

const GROUP: Group = {
  id: "g1",
  organization_id: "o1",
  name: "Engineering",
  description: null,
  icon: null,
  monthly_budget_usd: null,
  member_count: 4,
  created_at: "2026-10-01T00:00:00Z",
};
const PERIOD = { preset: "30d" as const, from: "2026-09-15", to: "2026-10-14" };

beforeEach(() => {
  data.usage = null;
});

function renderQuiet(props: Partial<Parameters<typeof QuietGroup>[0]> = {}) {
  render(
    <QuietGroup group={GROUP} period={PERIOD} {...props}>
      <p>the cards</p>
    </QuietGroup>,
  );
}

describe("a group's dashboard", () => {
  it("shows its cards while the usage loads and once it ran anything", () => {
    renderQuiet();
    expect(screen.getByText("the cards")).toBeInTheDocument();

    data.usage = { total_runs: 3 };
    renderQuiet();
    expect(screen.getAllByText("the cards")).toHaveLength(2);
  });

  it("says once that a quiet group ran nothing, and where to go", async () => {
    data.usage = { total_runs: 0 };
    const onWiden = vi.fn();
    renderQuiet({ onWiden });

    expect(screen.queryByText("the cards")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Engineering ran nothing in this period" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/None of its 4 members ran an agent/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the group/ })).toHaveAttribute(
      "href",
      "/groups/g1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Show the last 90 days" }));
    expect(onWiden).toHaveBeenCalled();
  });

  it("offers no wider window when it already shows the widest", () => {
    data.usage = { total_runs: 0 };
    renderQuiet();

    expect(screen.queryByRole("button", { name: "Show the last 90 days" })).toBeNull();
  });
});
