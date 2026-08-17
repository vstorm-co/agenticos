import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageCost } from "./message-cost";
import type { TurnUsage } from "@/types";

function usage(overrides: Partial<TurnUsage> = {}): TurnUsage {
  return {
    input_tokens: 12_400,
    output_tokens: 310,
    cost_usd: 0.0421,
    cost_is_partial: false,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    context: null,
    ...overrides,
  };
}

describe("MessageCost", () => {
  it("marks a cost that is only a floor, rather than reporting it as exact", () => {
    // A turn that reached a model with no price entry books that request at
    // zero, so the figure is short. Rendered identically to a measured one it is
    // a number that lies, which is the whole of #772.
    render(<MessageCost usage={usage({ cost_is_partial: true })} />);

    expect(screen.getByText(/≥ \$0\.0421/)).toBeInTheDocument();
  });

  it("says why in the tooltip, where there is room for a sentence", () => {
    render(<MessageCost usage={usage({ cost_is_partial: true })} />);

    expect(screen.getByTitle(/no price/)).toBeInTheDocument();
  });

  it("leaves an exactly measured cost unmarked", () => {
    render(<MessageCost usage={usage()} />);

    expect(screen.queryByText(/≥/)).toBeNull();
  });

  it("shows input and output separately, not as one total", () => {
    // 12,710 tokens says nothing about whether the turn read four documents or
    // wrote a long answer, and those cost differently.
    render(<MessageCost usage={usage()} />);

    expect(screen.getByText(/↓12,400/)).toBeVisible();
    expect(screen.getByText(/↑310/)).toBeVisible();
  });

  it("names which arrow is which for anybody who cannot guess", () => {
    render(<MessageCost usage={usage()} />);

    expect(screen.getByTitle("12,400 input · 310 output tokens")).toBeVisible();
  });

  it("prices the turn to four decimals, because most turns cost less than a cent", () => {
    render(<MessageCost usage={usage({ cost_usd: 0.0003 })} />);

    expect(screen.getByText(/\$0\.0003/)).toBeVisible();
  });
});
