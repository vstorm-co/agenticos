import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/types/agents";
import { JudgesSection, JudgeUsedBy } from "./judges-section";

const state = vi.hoisted(() => ({
  section: null as string | null,
  agents: [] as Partial<Agent>[],
  generator: null as Partial<Agent> | null,
  datasets: { datasets: [] as { name: string }[], total: 0, isLoading: false },
  perms: new Set<string>(),
  asked: [] as unknown[],
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useSearchParams: () =>
    new URLSearchParams(state.section === null ? "" : `section=${state.section}`),
}));
vi.mock("@/hooks/use-agents", () => ({
  useJudges: () => ({ agents: state.agents, total: state.agents.length }),
  useCaseGenerator: () => state.generator,
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
  window.localStorage.clear();
  state.section = null;
  state.agents = [{ id: "j1", name: "Eval judge", system_key: "eval_judge", kind: "judge" }];
  state.generator = null;
  state.datasets = { datasets: [], total: 0, isLoading: false };
  state.perms = new Set(["agents:edit", "datasets:view"]);
  state.asked = [];
});

/** The organization's judges sit folded under its agents, opened on demand. */
describe("JudgesSection", () => {
  it("starts folded, and opens onto cards an editor can open", async () => {
    render(<JudgesSection query="" agentsMatched />);
    const toggle = screen.getByRole("button", { name: "System agents (1)" });

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
    render(<JudgesSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (1)" }));

    expect(screen.getByTestId("card")).toHaveAttribute("data-can-edit", "false");
    expect(state.asked).toEqual([]);
  });

  it("shows each judge's model, and says when it has none", async () => {
    state.agents = [
      {
        id: "j1",
        name: "Eval judge",
        kind: "judge",
        published_model: {
          profile_id: "p1",
          provider: "openai",
          model: "gpt-4.1",
          label: "GPT-4.1",
        },
      },
      { id: "j2", name: "Draft judge", kind: "judge", published_model: null },
    ];
    render(<JudgesSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (2)" }));

    expect(screen.getByText("GPT-4.1")).toBeInTheDocument();
    expect(screen.getByText("No model yet")).toBeInTheDocument();
  });

  it("remembers being opened, in this browser", async () => {
    const { unmount } = render(<JudgesSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (1)" }));
    unmount();

    const { unmount: again } = render(<JudgesSection query="" agentsMatched />);
    expect(await screen.findByTestId("card")).toBeInTheDocument();
    expect(window.localStorage.getItem("agents.catalog.judges")).toBe("open");
    again();

    window.localStorage.setItem("agents.catalog.judges", "closed");
    render(<JudgesSection query="" agentsMatched />);
    expect(screen.getByRole("button", { name: "System agents (1)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens for a link to it, and for a search only judges answer", () => {
    state.section = "judges";
    const { unmount } = render(<JudgesSection query="" agentsMatched />);
    expect(screen.getByRole("button", { name: "System agents (1)" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    unmount();

    state.section = null;
    const { rerender } = render(<JudgesSection query="eval" agentsMatched={false} />);
    expect(screen.getByTestId("card")).toHaveTextContent("Eval judge");
    rerender(<JudgesSection query="eval" agentsMatched />);
    expect(screen.queryByTestId("card")).toBeNull();
    rerender(<JudgesSection query="nothing" agentsMatched={false} />);
    expect(screen.queryByTestId("card")).toBeNull();
  });

  it("keeps working where the browser refuses storage", async () => {
    const getItem = vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(<JudgesSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (1)" }));

    expect(screen.getByTestId("card")).toBeInTheDocument();
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it("lists the case generator beside the judges, and finds it by name", async () => {
    state.generator = {
      id: "g1",
      name: "Case generator",
      system_key: "case_generator",
      kind: "generator",
      published_model: { label: "Default" } as Agent["published_model"],
    };
    const { rerender } = render(<JudgesSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (2)" }));

    expect(screen.getAllByTestId("card").map((card) => card.textContent)).toEqual([
      expect.stringContaining("Eval judge"),
      expect.stringContaining("Case generator"),
    ]);
    expect(screen.getByText(/Drafts test cases for a dataset/)).toBeInTheDocument();

    rerender(<JudgesSection query="judge" agentsMatched />);
    expect(screen.getAllByTestId("card")).toHaveLength(1);
  });

  it("shows the case generator where the organization has no judge", () => {
    state.agents = [];
    state.generator = { id: "g1", name: "Case generator", kind: "generator" };
    render(<JudgesSection query="generator" agentsMatched={false} />);

    expect(screen.getByTestId("card")).toHaveTextContent("Case generator");
    expect(screen.queryByText("Judges")).toBeNull();
  });

  it("is absent while the organization has none", () => {
    state.agents = [];
    const { container } = render(<JudgesSection query="" agentsMatched />);

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
