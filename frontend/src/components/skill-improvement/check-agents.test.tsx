import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { checkAgent, skillCheck } from "@/test-utils/skill-improvement";
import { CheckAgents } from "./check-agents";

describe("CheckAgents", () => {
  it("leads with the agents to look at: worse, then unknown", () => {
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

    const names = screen.getAllByRole("link", { name: /^(Support|Refunds|Billing)$/ });
    expect(names.map((link) => link.textContent)).toEqual(["Refunds", "Billing", "Support"]);
    expect(screen.getByText("Not checked: its budget is spent.")).toBeInTheDocument();
  });

  it("says what each agent fixed and broke, with a link to the run", () => {
    render(<CheckAgents check={skillCheck({ agents: [checkAgent("Refunds", "worse")] })} />);

    expect(screen.getByText("Fixes 0 questions, breaks 1.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run on the skill's questions" })).toHaveAttribute(
      "href",
      "/agents/refunds/evals/run-refunds",
    );
  });

  it("says when an agent was checked only on the skill's questions", () => {
    render(
      <CheckAgents
        check={skillCheck({
          agents: [checkAgent("Sales", "no_change", { sample: "skill_set_only" })],
        })}
      />,
    );

    expect(screen.getByText(/Checked only on the skill's own questions/)).toBeInTheDocument();
  });

  it("counts the agents the reader cannot see, without naming them", () => {
    render(<CheckAgents check={skillCheck({ hidden: 2, hidden_unknown: 1 })} />);

    expect(
      screen.getByText("2 more agents you can't see were checked. 1 of them could not be."),
    ).toBeInTheDocument();
  });

  it("names a specialist that binds the skill for its agent, and runs on a sample", () => {
    const sampled = checkAgent("Support", "running", { via_specialist: "Refund helper" });
    sampled.stages = [
      { ...sampled.stages[0]!, kind: "dataset_sample", dataset_name: "Support cases" },
    ];
    render(<CheckAgents check={skillCheck({ agents: [sampled] })} />);

    expect(screen.getByText("Through its specialist Refund helper")).toBeInTheDocument();
    expect(screen.getByText("Checking")).toBeInTheDocument();
    expect(screen.queryByText(/^Fixes/)).toBeNull();
    expect(screen.getByRole("link", { name: "Run on a sample of Support cases" })).toBeVisible();
  });

  it("lists an agent and its specialist as two rows, and names no dataset the reader may not see", () => {
    const own = checkAgent("Support", "better");
    own.stages = [{ ...own.stages[0]!, kind: "dataset", dataset_name: null }];
    const specialist = checkAgent("Support", "no_change", { via_specialist: "Refund helper" });
    render(<CheckAgents check={skillCheck({ agents: [own, specialist] })} />);

    expect(screen.getAllByRole("link", { name: "Support" })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Run on the agent's questions" })).toBeVisible();
  });
});
