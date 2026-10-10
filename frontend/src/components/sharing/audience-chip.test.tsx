import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AudienceChip } from "./audience-chip";

describe("who a card says a resource is for (#2072)", () => {
  it.each([
    [{ visibility: "org", groups: ["Finance"] }, "Everyone"],
    [{ visibility: "private", groups: ["Finance", "Sales"] }, "Finance, Sales"],
    [{ visibility: "private", groups: ["Finance", "Sales", "HR"] }, "Finance, Sales +1"],
    [{ visibility: "private" }, "Private"],
  ])("%o reads %s", (props, label) => {
    render(<AudienceChip {...props} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
