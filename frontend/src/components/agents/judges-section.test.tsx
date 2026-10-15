import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/types/agents";
import { JudgesSection, JudgeUsedBy } from "./judges-section";

const state = vi.hoisted(() => ({
  agents: [] as Partial<Agent>[],
  datasets: { datasets: [] as { name: string }[], total: 0, isLoading: false },
  perms: new Set<string>(),
  asked: [] as unknown[],
}));
vi.mock("@/hooks/use-agents", () => ({
  useJudges: () => ({ agents: state.agents, total: state.agents.length }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: (query: unknown) => {
    state.asked.push(query);
    return state.datasets;
  },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.perms.has(perm) }),
}));
vi.mock("./agent-card", () => ({
  AgentCard: ({
    agent,
    canEdit,
    footer,
  }: {
    agent: Agent;
    canEdit: boolean;
    footer?: ReactNode;
  }) => (
    <div data-testid="card" data-can-edit={String(canEdit)}>
      {agent.name}
      {footer}
    </div>
  ),
}));

beforeEach(() => {
  state.agents = [{ id: "j1", name: "Eval judge", system_key: "eval_judge", kind: "judge" }];
  state.datasets = { datasets: [], total: 0, isLoading: false };
  state.perms = new Set(["agents:edit", "datasets:view"]);
  state.asked = [];
});

/** The organization's judges sit folded under its agents, opened on demand. */
describe("JudgesSection", () => {
  it("starts folded, and opens onto cards an editor can open", async () => {
    render(<JudgesSection />);
    const toggle = screen.getByRole("button", { name: "Judges (1)" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("card")).toBeNull();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("card")).toHaveTextContent("Eval judge");
    expect(screen.getByTestId("card")).toHaveAttribute("data-can-edit", "true");
    expect(screen.getByText("No dataset uses this judge yet.")).toBeInTheDocument();
    expect(state.asked).toContainEqual({ judge: "j1", limit: 3 });
  });

  it("names no dataset to somebody who may not read datasets", async () => {
    state.perms = new Set();
    render(<JudgesSection />);
    await userEvent.click(screen.getByRole("button", { name: "Judges (1)" }));

    expect(screen.getByTestId("card")).toHaveAttribute("data-can-edit", "false");
    expect(state.asked).toEqual([]);
  });

  it("is absent while the organization has none", () => {
    state.agents = [];
    const { container } = render(<JudgesSection />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("JudgeUsedBy", () => {
  it("names the first datasets and counts the rest", () => {
    state.datasets = {
      datasets: [{ name: "Refunds" }, { name: "Billing" }, { name: "Tone" }],
      total: 5,
      isLoading: false,
    };
    render(<JudgeUsedBy judgeId="j1" />);

    expect(screen.getByText("Used by Refunds, Billing, Tone and 2 more")).toBeInTheDocument();
  });

  it("names every dataset when there are few, and nothing while it loads", () => {
    state.datasets = { datasets: [{ name: "Refunds" }], total: 1, isLoading: false };
    const { rerender, container } = render(<JudgeUsedBy judgeId="j1" />);
    expect(screen.getByText("Used by Refunds")).toBeInTheDocument();

    state.datasets = { datasets: [], total: 0, isLoading: true };
    rerender(<JudgeUsedBy judgeId="j1" />);
    expect(container).toBeEmptyDOMElement();
  });
});
