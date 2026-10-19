import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageCost, RoundedCost } from "./message-cost";
import type { TurnUsage } from "@/types";

function usage(overrides: Partial<TurnUsage> = {}): TurnUsage {
  return {
    input_tokens: 12_400,
    output_tokens: 310,
    cost_usd: "0.0421",
    cost_is_partial: false,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    context: null,
    ...overrides,
  };
}

describe("MessageCost", () => {
  it("says how much of the input the cache served or took, where it did (#2170)", () => {
    render(<MessageCost usage={usage({ cache_read_tokens: 9_000, cache_write_tokens: 1_200 })} />);

    expect(
      screen.getByTitle(/9,000 read from the cache and 1,200 written to it/),
    ).toBeInTheDocument();
  });

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
    render(<MessageCost usage={usage({ cost_usd: "0.0003" })} />);

    expect(screen.getByText(/\$0\.0003/)).toBeVisible();
  });
});

describe("RoundedCost", () => {
  it("rounds to the cent and keeps the exact figure for the hover", () => {
    render(<RoundedCost usage={usage({ cost_usd: "0.0421" })} />);

    expect(screen.getByText("$0.04")).toHaveAttribute("title", "$0.0421");
    // The tokens are not part of what a reader of a conversation needs.
    expect(screen.queryByText(/↓/)).toBeNull();
  });

  it("says a turn under a cent cost under a cent, not nothing", () => {
    render(<RoundedCost usage={usage({ cost_usd: "0.0003" })} />);

    expect(screen.getByText("< $0.01")).toBeInTheDocument();
  });

  it("marks a floor, and says why on hover", () => {
    render(<RoundedCost usage={usage({ cost_usd: "0.0421", cost_is_partial: true })} />);

    expect(screen.getByText("≥ $0.04")).toHaveAttribute(
      "title",
      "$0.0421 - a floor: some model in this turn had no price",
    );
  });
});

describe("RoundedCost and the cache", () => {
  it("carries the cache split in its title too", () => {
    render(<RoundedCost usage={usage({ cache_read_tokens: 500, cache_write_tokens: 0 })} />);
    expect(screen.getByTitle(/500 read from the cache/)).toBeInTheDocument();
  });
});
