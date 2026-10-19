import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { UsedBy } from "./used-by";

const agent = (name: string) => ({ id: name, name });

describe("UsedBy", () => {
  it("says nothing when the response did not say", () => {
    const { container } = render(<UsedBy />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says plainly that nothing uses it yet", () => {
    render(<UsedBy agents={[]} />);
    expect(screen.getByText("Not used by any agent yet")).toBeInTheDocument();
  });

  it("names up to two agents and counts the rest", () => {
    render(<UsedBy agents={[agent("Billing"), agent("Sales"), agent("Support")]} />);
    expect(screen.getByText("Used by Billing, Sales and 1 more")).toBeInTheDocument();
  });

  it("names one agent alone", () => {
    render(<UsedBy agents={[agent("Support")]} />);
    expect(screen.getByText("Used by Support")).toBeInTheDocument();
  });
});
