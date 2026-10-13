import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AudienceChip } from "./audience-chip";

describe("who a card says a resource is for (#2072)", () => {
  it.each([
    [{ visibility: "org" }, "Everyone"],
    [{ visibility: "private", groups: ["Finance", "Sales"] }, "Finance, Sales"],
    [{ visibility: "private", groups: ["Finance", "Sales", "HR"] }, "Finance, Sales +1"],
    [{ visibility: "private" }, "Private"],
  ])("%o reads %s", (props, label) => {
    render(<AudienceChip {...props} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("a resource for everyone that belongs to a department (#2124)", () => {
  it("names both, so grouping by the department still shows on the card", () => {
    render(<AudienceChip visibility="org" groups={["Finance"]} />);
    expect(screen.getByText("Everyone")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
  });
});
