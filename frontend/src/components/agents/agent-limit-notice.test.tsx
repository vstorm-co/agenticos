import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentLimitNotice, isAtAgentLimit } from "./agent-limit-notice";

describe("isAtAgentLimit", () => {
  it("is never at a limit before the ceiling is read", () => {
    expect(isAtAgentLimit(null)).toBe(false);
  });

  it("is never at a limit the deployment does not set", () => {
    expect(isAtAgentLimit({ limit: null, held: null, at_limit: false })).toBe(false);
  });

  it("takes the server's word for whether the limit is reached", () => {
    // The server says so with or without the count: a caller who cannot see
    // every agent gets no count, and the answer is the same.
    expect(isAtAgentLimit({ limit: 5, held: 4, at_limit: false })).toBe(false);
    expect(isAtAgentLimit({ limit: 5, held: 5, at_limit: true })).toBe(true);
    expect(isAtAgentLimit({ limit: 5, held: null, at_limit: true })).toBe(true);
  });
});

describe("AgentLimitNotice", () => {
  it("names the limit and the count, and the ways out", () => {
    render(<AgentLimitNotice ceiling={{ limit: 1, held: 1, at_limit: true }} id="the-notice" />);

    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("id", "the-notice");
    expect(notice).toHaveTextContent(
      "This deployment allows 1 agent per organization, and this one has 1. Archive an agent you no longer run",
    );
  });

  it("names no count it was not given", () => {
    render(<AgentLimitNotice ceiling={{ limit: 3, held: null, at_limit: true }} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "This deployment allows 3 agents per organization, and this one has reached it.",
    );
  });
});
