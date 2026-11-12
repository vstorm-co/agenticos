import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckPlan, CheckProgress } from "./check-plan";
import { checkAgent } from "@/test-utils/skill-checks";

describe("CheckPlan", () => {
  it("says what each agent would be asked, or why it cannot be checked, and nothing waits", () => {
    render(
      <CheckPlan
        hidden={0}
        agents={[
          checkAgent({ name: "Online desk" }),
          checkAgent({ name: "Wholesale", state: "unknown", unknown_reason: "no_budget" }),
          checkAgent({ name: "Store info", sample: "skill_set_only" }),
        ]}
      />,
    );

    expect(screen.getByText("Not checked: its budget cannot cover the check.")).toBeInTheDocument();
    expect(screen.getByText(/none of this agent's questions opened the skill/)).toBeInTheDocument();
    expect(screen.getByText("Asked 6 questions")).toBeInTheDocument();
    expect(screen.queryByText("Waiting")).toBeNull();
  });

  it("says an agent was not measured for a reason it does not know by name", () => {
    render(
      <CheckPlan
        hidden={0}
        agents={[
          checkAgent({
            state: "unknown",
            unknown_reason: "evidence_only" as unknown as "failed",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Not checked: the check could not measure it.")).toBeInTheDocument();
  });

  it("counts the agents the reader may not see, and never names them", () => {
    render(<CheckPlan hidden={2} agents={[]} />);

    expect(
      screen.getByText("2 more agents use this skill that you cannot see."),
    ).toBeInTheDocument();
  });
});

describe("CheckProgress", () => {
  it("says how many agents are done while the check runs", () => {
    render(
      <CheckProgress
        agents={[
          checkAgent({ name: "Online desk", state: "better" }),
          checkAgent({ name: "Gift shop", state: "running" }),
          checkAgent({ name: "Wholesale", state: "queued" }),
        ]}
      />,
    );

    expect(screen.getByText("1 of 3 agents checked")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Agents checked" })).toHaveAttribute(
      "aria-valuenow",
      "1",
    );
  });

  it("draws nothing for a check with no agent the reader may see", () => {
    const { container } = render(<CheckProgress agents={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
