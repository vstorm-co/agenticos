import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DelegationHandoff } from "./delegation-handoff";

const parent = { id: "p", slug: "chief-of-staff", name: "Chief of Staff" };
const finance = { id: "f", slug: "finance-analyst", name: "Finance Analyst" };

/** The team at work: the brief travelling out, the answer coming back. */
describe("the handoff strip", () => {
  it("draws nothing for no delegates", () => {
    const { container } = render(<DelegationHandoff parent={parent} lanes={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("sends the brief down a working delegate's lane, and hops it", () => {
    const { container } = render(
      <DelegationHandoff
        parent={parent}
        lanes={[{ key: "1", delegate: finance, status: "running" }]}
      />,
    );

    expect(container.querySelectorAll(".handoff-out")).toHaveLength(3);
    expect(container.querySelector(".blob-hop")).not.toBeNull();
    expect(container.querySelector(".handoff-pulse")).not.toBeNull();
  });

  it("sends the answer back once it is in, and stops", () => {
    const { container } = render(
      <DelegationHandoff
        parent={parent}
        lanes={[{ key: "1", delegate: finance, status: "completed" }]}
      />,
    );

    expect(container.querySelector(".handoff-back")).not.toBeNull();
    expect(container.querySelector(".handoff-out")).toBeNull();
    expect(container.querySelector(".blob-hop")).toBeNull();
  });

  it("over the live panels, is faces only, named on hover", () => {
    render(
      <DelegationHandoff
        named={false}
        lanes={[{ key: "1", delegate: finance, status: "running" }]}
      />,
    );

    expect(screen.queryByText("Finance Analyst")).toBeNull();
    expect(screen.getByTitle("Finance Analyst")).toBeInTheDocument();
  });
});
