import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReachedAgent } from "@/types/authoring";
import { GoesLive } from "./goes-live";

function agent(overrides: Partial<ReachedAgent> = {}): ReachedAgent {
  return {
    id: "a-1",
    name: "Refund desk",
    environments: ["production"],
    runs_now: [],
    runs_now_count: 0,
    at_promotion: [],
    at_promotion_count: 0,
    ...overrides,
  };
}

describe("GoesLive", () => {
  it("says where it goes live, what runs now and what waits for a promotion", () => {
    render(
      <GoesLive
        reaches={[
          agent({
            environments: ["production", "staging"],
            runs_now: ["Refund smoke"],
            runs_now_count: 1,
            at_promotion: ["Nightly"],
            at_promotion_count: 1,
          }),
          agent({ id: "a-2", name: "Clerk" }),
        ]}
        hidden={1}
      />,
    );

    expect(
      screen.getByText(
        "Goes live now for Refund desk (production and staging), Clerk (production), and 1 agent you cannot see.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Runs now: Refund smoke.")).toBeVisible();
    expect(screen.getByText("Nightly checks it at the next promotion.")).toBeVisible();
  });

  it("counts the suites a reader may not name, and says nothing of runs that will not happen", () => {
    const { rerender } = render(
      <GoesLive reaches={[agent({ runs_now_count: 2, at_promotion_count: 3 })]} hidden={0} />,
    );
    expect(screen.getByText("Runs now: 2 eval suites.")).toBeVisible();
    expect(screen.getByText("3 eval suites check it at the next promotion.")).toBeVisible();

    rerender(<GoesLive reaches={[agent()]} hidden={0} />);
    expect(screen.queryByText(/Runs now/)).toBeNull();
    expect(screen.queryByText(/next promotion/)).toBeNull();
  });

  it("says when no published agent reads it", () => {
    render(<GoesLive reaches={[]} hidden={0} />);

    expect(
      screen.getByText("No published agent reads it yet, so applying it changes no answers today."),
    ).toBeVisible();
  });
});
