import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckAgents } from "./check-agents";
import { checkAgent } from "@/test-utils/skill-checks";

describe("CheckAgents", () => {
  it("says how each agent came out and what it was asked", () => {
    render(
      <CheckAgents
        hidden={0}
        agents={[
          checkAgent({ name: "Online desk", state: "better" }),
          checkAgent({ name: "Gift shop", state: "worse" }),
          checkAgent({ name: "Wholesale", state: "unknown", unknown_reason: "no_budget" }),
          checkAgent({ name: "Store info", state: "no_change", sample: "skill_set_only" }),
        ]}
      />,
    );

    expect(screen.getByText("Better")).toBeInTheDocument();
    expect(screen.getByText("Worse")).toBeInTheDocument();
    expect(screen.getByText("Not checked: its budget cannot cover the check.")).toBeInTheDocument();
    expect(screen.getByText(/none of this agent's questions opened the skill/)).toBeInTheDocument();
    expect(screen.getAllByText("Asked 6 questions")).toHaveLength(2);
  });

  it("counts the agents the reader may not see, and never names them", () => {
    render(<CheckAgents hidden={2} agents={[]} />);

    expect(
      screen.getByText("2 more agents use this skill that you cannot see."),
    ).toBeInTheDocument();
  });
});
