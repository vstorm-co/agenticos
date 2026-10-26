import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentLimitNotice, isAtAgentLimit } from "./agent-limit-notice";

describe("isAtAgentLimit", () => {
  it("is never at a limit the deployment does not set", () => {
    expect(isAtAgentLimit(null)).toBe(false);
  });

  it("is below the limit while there is room for one more", () => {
    expect(isAtAgentLimit({ limit: 5, held: 4 })).toBe(false);
  });

  it("is at the limit at it and past it", () => {
    // Past it is possible: an administrator can lower the limit under a count.
    expect(isAtAgentLimit({ limit: 5, held: 5 })).toBe(true);
    expect(isAtAgentLimit({ limit: 3, held: 5 })).toBe(true);
  });
});

describe("AgentLimitNotice", () => {
  it("names the limit and the count, and the ways out", () => {
    render(<AgentLimitNotice ceiling={{ limit: 1, held: 1 }} id="the-notice" />);

    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("id", "the-notice");
    expect(notice).toHaveTextContent(
      "This deployment allows 1 agent per organization, and this one has 1. Archive an agent you no longer run",
    );
  });
});
