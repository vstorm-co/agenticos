import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { checkAgent, skillCheck } from "@/test-utils/skill-improvement";
import type { EvalComparison } from "@/types/eval-runs";
import { CheckAgents } from "./check-agents";

const compared = vi.hoisted(() => ({
  comparison: undefined as Partial<EvalComparison> | undefined,
  error: null as Error | null,
}));
const asked = vi.hoisted(() => ({ enabled: [] as boolean[] }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalComparison: (_run: string, options: { enabled?: boolean } = {}) => {
    asked.enabled.push(options.enabled ?? true);
    return compared;
  },
}));

/** Opens every agent's row, as a person reading them all would. */
async function openAll() {
  for (const toggle of screen.getAllByRole("button", { name: /^Details of / })) {
    await userEvent.click(toggle);
  }
}

beforeEach(() => {
  localStorage.clear();
  compared.comparison = undefined;
  compared.error = null;
  asked.enabled = [];
});

describe("CheckAgents", () => {
  it("leads with the agents to look at: worse, then unknown", async () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [
            checkAgent("Support", "better"),
            checkAgent("Refunds", "worse"),
            checkAgent("Billing", "unknown", { unknown_reason: "no_budget", stages: [] }),
          ],
        })}
      />,
    );

    const rows = screen.getAllByRole("button", { name: /^Details of / });
    expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Details of Refunds",
      "Details of Billing",
      "Details of Support",
    ]);
    await openAll();
    expect(screen.getByText("Not checked: its budget is spent.")).toBeInTheDocument();
  });

  it("says what each agent fixed and broke, with a link to the run", async () => {
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    await openAll();

    expect(screen.getByText("Fixes 0 questions, breaks 1.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run on the skill's questions" })).toHaveAttribute(
      "href",
      "/agents/refunds/evals/run-refunds",
    );
  });

  it("says when an agent was checked only on the skill's questions", async () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [checkAgent("Sales", "no_change", { sample: "skill_set_only" })],
        })}
      />,
    );
    await openAll();

    expect(screen.getByText(/Checked only on the skill's own questions/)).toBeInTheDocument();
  });

  it("counts the agents the reader cannot see, without naming them", () => {
    render(<CheckAgents check={skillCheck({ agents: [], hidden: 2, hidden_unknown: 1 })} />);
    expect(screen.queryByText(/better$/)).toBeNull();

    expect(
      screen.getByText("2 more agents you can't see were checked. 1 of them could not be."),
    ).toBeInTheDocument();
  });

  it("names a specialist that binds the skill for its agent, and runs on a sample", async () => {
    const sampled = checkAgent("Support", "running", { via_specialist: "Refund helper" });
    sampled.stages = [
      { ...sampled.stages[0]!, kind: "dataset_sample", dataset_name: "Support cases" },
    ];
    render(<CheckAgents check={skillCheck({ agents: [sampled] })} />);
    await openAll();

    expect(screen.getByText("Through its specialist Refund helper")).toBeInTheDocument();
    expect(screen.getByText("Checking")).toBeInTheDocument();
    expect(screen.queryByText(/^Fixes/)).toBeNull();
    expect(screen.getByRole("link", { name: "Run on a sample of Support cases" })).toBeVisible();
  });

  it("lists an agent and its specialist as two rows, and names no dataset the reader may not see", async () => {
    const own = checkAgent("Support", "better");
    own.stages = [{ ...own.stages[0]!, kind: "dataset", dataset_name: null }];
    const specialist = checkAgent("Support", "no_change", { via_specialist: "Refund helper" });
    render(<CheckAgents check={skillCheck({ agents: [own, specialist] })} />);
    await openAll();

    expect(screen.getAllByRole("button", { name: "Details of Support" })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Run on the agent's questions" })).toBeVisible();
  });

  it("sums the agents up above them, counting the ones still checked only while there are any", () => {
    const { rerender } = render(
      <CheckAgents
        check={skillCheck({
          agents: [
            checkAgent("Support", "better"),
            checkAgent("Sales", "within_noise"),
            checkAgent("Billing", "no_change"),
            checkAgent("Refunds", "worse"),
            checkAgent("Orders", "unknown", { unknown_reason: "no_budget" }),
          ],
        })}
      />,
    );
    for (const count of ["1 worse", "1 not known", "2 no change", "1 better"]) {
      expect(screen.getByText(count)).toBeVisible();
    }
    expect(screen.queryByText(/still checking/)).toBeNull();

    rerender(
      <CheckAgents
        check={skillCheck({
          agents: [checkAgent("Support", "queued"), checkAgent("Sales", "running")],
        })}
      />,
    );
    expect(screen.getByText("2 still checking")).toBeVisible();
  });

  it("marks an agent seen once its details are opened, and remembers it for the check", async () => {
    const check = skillCheck();
    const { unmount } = render(<CheckAgents check={check} />);
    expect(screen.getByText("None of 2 agents looked at yet")).toBeVisible();
    expect(screen.queryByText("Seen")).toBeNull();

    const toggle = screen.getByRole("button", { name: "Details of Support" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Looked at 1 of 2 agents")).toBeVisible();
    await userEvent.click(toggle);
    expect(screen.getAllByText("Seen")).toHaveLength(1);

    unmount();
    render(<CheckAgents check={check} />);
    expect(screen.getByText("Looked at 1 of 2 agents")).toBeVisible();
    render(<CheckAgents check={skillCheck({ id: "c2" })} />);
    expect(screen.getByText("None of 2 agents looked at yet")).toBeVisible();
  });

  it("still marks what was seen when the browser refuses to store it", async () => {
    localStorage.setItem("skill-check-seen:c1", "{not json");
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<CheckAgents check={skillCheck()} />);
    await userEvent.click(screen.getByRole("button", { name: "Details of Sales" }));
    expect(screen.getByText("Seen")).toBeVisible();
    setItem.mockRestore();
  });

  it("opens a row from anywhere on it, and by keyboard", async () => {
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    const row = screen.getByRole("button", { name: "Details of Refunds" });

    await userEvent.click(screen.getByText("Refunds"));
    expect(row).toHaveAttribute("aria-expanded", "true");
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(row).toHaveAttribute("aria-expanded", "false");
    await userEvent.keyboard(" ");
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Open Refunds" })).toHaveAttribute(
      "href",
      "/agents/refunds",
    );
  });

  it("breaks an older check's stages down from their runs, an unfinished case as not known", async () => {
    const flip = (kind: string) => ({ flip: kind });
    compared.comparison = {
      cases: [
        flip("fixed"),
        flip("fixed"),
        flip("regression"),
        flip("unchanged"),
        flip("incomplete"),
      ] as EvalComparison["cases"],
      not_compared: 2,
    };
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    await openAll();

    expect(screen.getByText("2 better · 1 same · 1 worse · 3 not known")).toBeInTheDocument();
    expect(asked.enabled).toContain(true);
  });

  it("reads the counts a check kept without asking the run", async () => {
    const row = checkAgent("Refunds", "worse");
    row.stages = [
      {
        ...row.stages[0]!,
        counts: { compared: 6, fixed: 1, broken: 1, unchanged: 4, unknown: 2 },
      },
    ];
    render(<CheckAgents check={skillCheck({ agents: [row] })} />);
    await openAll();

    expect(screen.getByText("1 better · 4 same · 1 worse · 2 not known")).toBeInTheDocument();
    expect(asked.enabled.every((enabled) => !enabled)).toBe(true);
  });

  it("says while a stage's results are read, and when they cannot be", async () => {
    const { rerender } = render(
      <CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />,
    );
    await openAll();
    expect(screen.getByText("Reading the results…")).toBeInTheDocument();

    compared.error = new Error("Forbidden");
    rerender(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    expect(screen.getByText("Its results could not be read.")).toBeInTheDocument();
  });
});
