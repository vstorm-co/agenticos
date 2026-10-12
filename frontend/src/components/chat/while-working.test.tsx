import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WaitingSteers } from "./while-working";

describe("a message typed while the agent works (#2087)", () => {
  it("lists the corrections on their way, and nothing when there are none", () => {
    const { rerender, container } = render(<WaitingSteers steers={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<WaitingSteers steers={[{ id: "s1", text: "use the EU numbers" }]} />);
    expect(screen.getByText("use the EU numbers")).toBeInTheDocument();
    expect(screen.getByText(/reads this at its next step/)).toBeInTheDocument();
  });
});
