import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/types/agents";
import { SystemAgentsSection, JudgeUsedBy } from "./system-agents-section";

const state = vi.hoisted(() => ({
  section: null as string | null,
  agents: [] as Partial<Agent>[],
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
  useSystemAgents: () => ({
    groups: (["judge", "drafter", "generator"] as const).map((kind) => ({
      kind,
      agents: state.agents.filter((agent) => agent.kind === kind),
    })),
    total: state.agents.length,
  }),
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
  state.datasets = { datasets: [], total: 0, isLoading: false };
  state.perms = new Set(["agents:edit", "datasets:view"]);
  state.asked = [];
});

/** The organization's system agents sit folded under its agents, opened on demand. */
describe("SystemAgentsSection", () => {
  it("starts folded, and opens onto cards an editor can open", async () => {
    render(<SystemAgentsSection query="" agentsMatched />);
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
    render(<SystemAgentsSection query="" agentsMatched />);
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
    render(<SystemAgentsSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (2)" }));

    expect(screen.getByText("GPT-4.1")).toBeInTheDocument();
    expect(screen.getByText("No model yet")).toBeInTheDocument();
  });

  it("remembers being opened, in this browser", async () => {
    const { unmount } = render(<SystemAgentsSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (1)" }));
    unmount();

    const { unmount: again } = render(<SystemAgentsSection query="" agentsMatched />);
    expect(await screen.findByTestId("card")).toBeInTheDocument();
    expect(window.localStorage.getItem("agents.catalog.system")).toBe("open");
    again();

    window.localStorage.setItem("agents.catalog.system", "closed");
    render(<SystemAgentsSection query="" agentsMatched />);
    expect(screen.getByRole("button", { name: "System agents (1)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens for a link to it, and for a search only system agents answer", () => {
    state.section = "system";
    const { unmount } = render(<SystemAgentsSection query="" agentsMatched />);
    expect(screen.getByRole("button", { name: "System agents (1)" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    unmount();

    state.section = null;
    const { rerender } = render(<SystemAgentsSection query="eval" agentsMatched={false} />);
    expect(screen.getByTestId("card")).toHaveTextContent("Eval judge");
    rerender(<SystemAgentsSection query="eval" agentsMatched />);
    expect(screen.queryByTestId("card")).toBeNull();
    rerender(<SystemAgentsSection query="nothing" agentsMatched={false} />);
    expect(screen.queryByTestId("card")).toBeNull();
  });

  it("keeps working where the browser refuses storage", async () => {
    const getItem = vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(<SystemAgentsSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (1)" }));

    expect(screen.getByTestId("card")).toBeInTheDocument();
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it("groups the agents by kind, and leaves out a kind with none", async () => {
    state.agents = [
      { id: "j1", name: "Eval judge", kind: "judge" },
      { id: "d1", name: "Knowledge gap drafter", kind: "drafter", published_model: null },
      { id: "c1", name: "Case generator", kind: "generator", published_model: null },
    ];
    const { unmount } = render(<SystemAgentsSection query="" agentsMatched />);
    await userEvent.click(screen.getByRole("button", { name: "System agents (3)" }));

    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(["Judges (1)", "Gap drafter (1)", "Case generator (1)"]);
    // Only a judge names the datasets it grades.
    expect(state.asked).toEqual([{ judge: "j1", limit: 3 }]);
    unmount();

    state.agents = [{ id: "d1", name: "Knowledge gap drafter", kind: "drafter" }];
    render(<SystemAgentsSection query="" agentsMatched />);
    expect(screen.getByRole("heading", { name: "Gap drafter (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Judges/ })).toBeNull();
  });

  it("narrows each kind by the search", async () => {
    state.agents = [
      { id: "j1", name: "Eval judge", kind: "judge" },
      { id: "d1", name: "Knowledge gap drafter", kind: "drafter" },
    ];
    render(<SystemAgentsSection query="drafter" agentsMatched={false} />);

    expect(screen.getByTestId("card")).toHaveTextContent("Knowledge gap drafter");
    expect(screen.queryByRole("heading", { name: /Judges/ })).toBeNull();
  });

  it("is absent while the organization has none", () => {
    state.agents = [];
    const { container } = render(<SystemAgentsSection query="" agentsMatched />);

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
