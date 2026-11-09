import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { checkAgent, skillCheck } from "@/test-utils/skill-improvement";
import type { EvalComparison } from "@/types/eval-runs";
import { ReadOnlyProvider } from "@/components/improvement/read-only";
import { CheckAgents } from "./check-agents";
import type { AgentCheckState } from "@/types/skill-checks";
import catalog from "../../../messages/en.json";

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
vi.mock("./add-test-questions", () => ({
  AddTestQuestions: ({ skillId }: { skillId: string }) => <p>Add questions to {skillId}</p>,
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
    expect(screen.getAllByText("Not checked: its budget is spent.")).toHaveLength(2);
  });

  it("keeps an agent unknown for a reason it does not know by name, and says so", async () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [
            checkAgent("Billing", "unknown", {
              unknown_reason: "evidence_only" as unknown as "failed",
              stages: [],
            }),
          ],
        })}
      />,
    );

    await openAll();
    expect(screen.getAllByText("Not checked: the check could not measure it.")).toHaveLength(2);
  });

  it("offers what lets each unknown agent be checked, and says when its own were not asked", async () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [
            checkAgent("Billing", "unknown", { unknown_reason: "unscorable" }),
            checkAgent("Refunds", "unknown", { unknown_reason: "all_evidence", stages: [] }),
            checkAgent("Support", "worse", { sample: "own_not_asked" }),
          ],
        })}
      />,
    );

    expect(screen.getByText("Add questions to k1")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /^Set up grading on / })[0]).toHaveAttribute(
      "href",
      expect.stringMatching(/\/datasets\/.+\?tab=grading$/),
    );
    await openAll();
    expect(screen.getByText(/the skill's questions already showed it worse/)).toBeInTheDocument();
    expect(
      screen.getAllByText(/every question came from the conversations the change was learned/),
    ).toHaveLength(2);
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

  it("keeps a label for every state an agent's check can reach, for the pages that name it", () => {
    const states: AgentCheckState[] = [
      "queued",
      "running",
      "better",
      "no_change",
      "within_noise",
      "worse",
      "unknown",
    ];
    for (const state of states) expect(catalog.skillImprovement.agents.state).toHaveProperty(state);
  });

  it("names an agent within the test's noise as no change, as its group and count do", () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [checkAgent("Sales", "within_noise"), checkAgent("Billing", "no_change")],
        })}
      />,
    );

    expect(screen.getByText("2 no change")).toBeVisible();
    expect(screen.getAllByText("No change", { selector: "span" })).toHaveLength(2);
    expect(screen.queryByText("Within noise")).toBeNull();
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
    const check = skillCheck({
      agents: [checkAgent("Refunds", "worse"), checkAgent("Support", "better")],
    });
    const { unmount } = render(<CheckAgents check={check} />);
    expect(screen.getByText("Left to look at: 1 of 1")).toBeVisible();
    expect(screen.queryByText("Seen")).toBeNull();

    const toggle = screen.getByRole("button", { name: "Details of Refunds" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Left to look at: 0 of 1")).toBeVisible();
    await userEvent.click(toggle);
    expect(screen.getAllByText("Seen")).toHaveLength(1);

    unmount();
    render(<CheckAgents check={check} />);
    expect(screen.getByText("Left to look at: 0 of 1")).toBeVisible();
    render(<CheckAgents check={{ ...check, id: "c2" }} />);
    expect(screen.getByText("Left to look at: 1 of 1")).toBeVisible();
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

  it("breaks an older check's stages down from their runs, an unfinished or changed case as not known", async () => {
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
      changed: 1,
    };
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    await openAll();

    expect(screen.getByText("2 better · 1 same · 1 worse · 4 not known")).toBeInTheDocument();
    expect(asked.enabled).toContain(true);
  });

  it("reads a stage's kept counts without asking its run, and says where agents broke", async () => {
    const counts = (broken: number) => ({
      compared: 6,
      fixed: 1,
      broken,
      unchanged: 4,
      unknown: 2,
    });
    const worse = (name: string, broken: number) => {
      const row = checkAgent(name, "worse");
      row.stages = [{ ...row.stages[0]!, kind: "skill_set", counts: counts(broken) }];
      return row;
    };
    render(<CheckAgents check={skillCheck({ agents: [worse("Refunds", 1), worse("Desk", 0)] })} />);

    expect(
      screen.getByText("1 of 2 broke on the skill's own questions, which every agent shares."),
    ).toBeVisible();
    await openAll();
    expect(screen.getByText("1 better · 4 same · 1 worse · 2 not known")).toBeInTheDocument();
    expect(asked.enabled.every((enabled) => !enabled)).toBe(true);
  });

  it("says an agent's first-answer flips went unconfirmed when it is within the noise", async () => {
    const noisy = checkAgent("Store", "within_noise", { fixed: 2, broken: 0, noisy: true });
    noisy.stages = [
      {
        ...noisy.stages[0]!,
        kind: "skill_set",
        counts: { compared: 6, fixed: 2, broken: 0, unchanged: 4, unknown: 0 },
      },
    ];
    render(<CheckAgents check={skillCheck({ agents: [noisy] })} />);

    await openAll();
    expect(
      screen.getByText(
        "2 questions looked fixed and 0 looked broken at first, but asking them again did not confirm it, so the agent counts as no change.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("At first: 2 better · 4 same · 0 worse · 0 not known"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Fixes/)).toBeNull();
  });

  it("says nothing of where agents broke until each one's counts are kept", () => {
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);
    expect(screen.queryByText(/broke on the skill's own questions/)).toBeNull();
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

  describe("with many agents", () => {
    const many = () =>
      skillCheck({
        agents: [
          checkAgent("Refunds", "worse", { broken: 1 }),
          checkAgent("Returns", "worse", { broken: 4 }),
          checkAgent("Wholesale", "unknown", { unknown_reason: "no_questions", stages: [] }),
          checkAgent("Kiosk", "unknown", { unknown_reason: "no_budget", stages: [] }),
          checkAgent("Store", "unknown", { unknown_reason: null, stages: [] }),
          checkAgent("Online", "better", { fixed: 1 }),
          checkAgent("Counter", "better", { fixed: 5 }),
          checkAgent("Billing", "no_change"),
          checkAgent("Sales", "within_noise"),
        ],
      });
    const names = () =>
      screen
        .queryAllByRole("button", { name: /^Details of / })
        .map((row) => row.getAttribute("aria-label")!.replace("Details of ", ""));

    it("opens the worse and the unknown, counts the rest, and sorts each group", async () => {
      render(<CheckAgents check={many()} />);

      expect(names()).toEqual(["Returns", "Refunds", "Wholesale", "Kiosk", "Store"]);
      expect(screen.getByText("Left to look at: 5 of 5")).toBeVisible();
      expect(screen.getByText("Add questions to k1")).toBeVisible();
      expect(screen.getByRole("button", { name: "No change (2)" })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      await userEvent.click(screen.getByRole("button", { name: "Better (2)" }));
      expect(names().slice(-2)).toEqual(["Counter", "Online"]);
      await userEvent.click(screen.getByRole("button", { name: "Worse (2)" }));
      expect(names()).not.toContain("Returns");
    });

    it("filters by how they came out, by name, and to the ones not looked at", async () => {
      render(<CheckAgents check={many()} />);
      const filters = screen.getByRole("group", { name: "Show only" });

      await userEvent.click(within(filters).getByRole("button", { name: "2 no change" }));
      expect(names()).toEqual(["Billing", "Sales"]);
      await userEvent.click(within(filters).getByRole("button", { name: "2 no change" }));

      await userEvent.type(screen.getByRole("searchbox", { name: "Find an agent" }), "count");
      expect(names()).toEqual(["Counter"]);
      await userEvent.clear(screen.getByRole("searchbox", { name: "Find an agent" }));

      await userEvent.click(screen.getByRole("button", { name: "Details of Returns" }));
      await userEvent.click(screen.getByRole("checkbox", { name: "Only the ones not looked at" }));
      expect(names()).not.toContain("Returns");
      expect(screen.getByText("Left to look at: 4 of 5")).toBeVisible();

      await userEvent.type(screen.getByRole("searchbox", { name: "Find an agent" }), "nobody");
      expect(screen.getByText("No agent matches.")).toBeVisible();
    });

    it("keeps a row opened under Only the ones not looked at, so it can be read", async () => {
      render(<CheckAgents check={many()} />);
      await userEvent.click(screen.getByRole("checkbox", { name: "Only the ones not looked at" }));

      await userEvent.click(screen.getByRole("button", { name: "Details of Refunds" }));
      expect(screen.getByRole("button", { name: "Details of Refunds" })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      expect(screen.getByRole("link", { name: "Open Refunds" })).toBeVisible();

      await userEvent.click(screen.getByRole("checkbox", { name: "Only the ones not looked at" }));
      await userEvent.click(screen.getByRole("checkbox", { name: "Only the ones not looked at" }));
      expect(names()).not.toContain("Refunds");
    });

    it("offers writing test questions only to someone who may edit the skill", () => {
      render(
        <ReadOnlyProvider value="viewOnly">
          <CheckAgents check={many()} />
        </ReadOnlyProvider>,
      );
      expect(
        screen.getByText(
          "Not checked: it has no test questions where it loaded the skill, and the skill has none of its own.",
        ),
      ).toBeVisible();
      expect(screen.queryByText("Add questions to k1")).toBeNull();
    });

    it("offers setting up grading only to someone who may edit the skill", () => {
      render(
        <ReadOnlyProvider value="viewOnly">
          <CheckAgents
            check={skillCheck({
              agents: [checkAgent("Billing", "unknown", { unknown_reason: "unscorable" })],
            })}
          />
        </ReadOnlyProvider>,
      );
      expect(screen.queryByRole("link", { name: /^Set up grading on / })).toBeNull();
    });

    it("says when nothing worse or unknown is left to look at", () => {
      render(
        <CheckAgents
          check={skillCheck({
            agents: [checkAgent("Support", "better"), checkAgent("Sales", "no_change")],
          })}
        />,
      );
      expect(screen.getByText("Nothing worse or unknown to look at")).toBeVisible();
    });
  });
});
