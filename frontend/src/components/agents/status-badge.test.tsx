import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AgentStatusBadge, RunStatusBadge } from "./status-badge";

describe("AgentStatusBadge", () => {
  it.each(["draft", "published", "archived"] as const)("renders %s", (status) => {
    render(<AgentStatusBadge status={status} />);
    expect(screen.getByText(status)).toBeInTheDocument();
  });
});

describe("RunStatusBadge", () => {
  it("spells out what awaiting_approval means", () => {
    // "awaiting_approval" tells an engineer something; "waiting for approval"
    // tells the person who has to act.
    render(<RunStatusBadge status="awaiting_approval" />);
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
  });

  it("does not present a budget stop as a failure", () => {
    // It is the platform working as designed. Colouring it like a crash sends
    // operators chasing a problem that is not one.
    const { container } = render(<RunStatusBadge status="budget_exceeded" />);
    expect(screen.getByText("Stopped by budget")).toBeInTheDocument();
    expect(container.querySelector('[class*="destructive"]')).toBeNull();
  });

  it("does present a failure as a failure", () => {
    const { container } = render(<RunStatusBadge status="failed" />);
    expect(container.querySelector('[class*="destructive"]')).not.toBeNull();
  });

  it.each([
    ["completed", "Completed"],
    ["running", "Running"],
    ["cancelled", "Cancelled"],
  ] as const)("renders %s", (status, label) => {
    render(<RunStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
