import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { checkAgent, skillCheck } from "@/test-utils/skill-improvement";
import type { SkillContinuationEstimate } from "@/types/skill-improvement";
import { CheckEstimate } from "./check-estimate";

const QUOTE: SkillContinuationEstimate = {
  mode: "next_step",
  number: 1,
  total_usd: "0.10",
  budget_usd: "1.00",
  affordable: true,
  candidate_hash: "h",
};

describe("CheckEstimate", () => {
  it("names the agents a check runs on and the ones it cannot, with the reason", () => {
    const quote: SkillContinuationEstimate = {
      ...QUOTE,
      check_estimate: {
        ...skillCheck(),
        agents: [
          checkAgent("Support", "queued"),
          checkAgent("Billing", "unknown", { unknown_reason: "inconclusive" }),
        ],
        hidden: 2,
        description_changed: true,
      },
    };
    render(<CheckEstimate quote={quote} />);

    expect(screen.getByText("It will be checked on 1 agent: Support.")).toBeVisible();
    expect(
      screen.getByText("Billing cannot be checked: its run could not grade every answer."),
    ).toBeVisible();
    expect(screen.getByText("2 more agents you can't see use this line.")).toBeVisible();
    expect(screen.getByText(/The description changed/)).toBeVisible();
  });

  it("says nothing for a step that is not a check", () => {
    const { container } = render(<CheckEstimate quote={QUOTE} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says a check failed for an agent the estimate gives no reason for", () => {
    const quote: SkillContinuationEstimate = {
      ...QUOTE,
      check_estimate: {
        ...skillCheck(),
        agents: [checkAgent("Billing", "unknown", { unknown_reason: null })],
        hidden: 0,
      },
    };
    render(<CheckEstimate quote={quote} />);

    expect(screen.getByText("Billing cannot be checked: its check failed.")).toBeVisible();
  });
});
