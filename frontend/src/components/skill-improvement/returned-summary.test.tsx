import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReturnedToMain } from "@/types/skill-merge";
import { ReturnedSummary } from "./returned-summary";

const agent = (name: string, overrides: Partial<ReturnedToMain["agents"][number]> = {}) => ({
  agent: { id: name.toLowerCase(), name },
  published: true,
  agent_version: 3,
  refused: null,
  ...overrides,
});

describe("ReturnedSummary", () => {
  it("names who moved, who waits in a draft and who stays on the fork, and why", () => {
    render(
      <ReturnedSummary
        returned={{
          agents: [
            agent("Desk"),
            agent("Shop", { published: false, agent_version: null }),
            agent("Outlet", {
              published: false,
              refused: "It reads the fork through a specialist",
            }),
          ],
          hidden: 2,
          remaining: 3,
          archived: false,
        }}
      />,
    );

    expect(screen.getByText("Moved to main and published: Desk.")).toBeVisible();
    expect(
      screen.getByText("Moved to main in its draft, which waits to be published: Shop."),
    ).toBeVisible();
    expect(
      screen.getByText("Outlet stays on the fork: It reads the fork through a specialist"),
    ).toBeVisible();
    expect(screen.getByText("2 agents you cannot see were left as they were.")).toBeVisible();
    expect(screen.getByText("3 agents still read the fork, so it was not archived.")).toBeVisible();
  });

  it("says the fork was archived once nobody reads it", () => {
    render(
      <ReturnedSummary
        returned={{ agents: [agent("Desk")], hidden: 0, remaining: 0, archived: true }}
      />,
    );
    expect(screen.getByText("Nobody reads the fork any more, so it was archived.")).toBeVisible();
    expect(screen.queryByText(/cannot see/)).not.toBeInTheDocument();
  });
});
