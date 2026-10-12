import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SendModePicker, SideAnswers, WaitingSteers } from "./while-working";

describe("what a message typed while the agent works does (#2087)", () => {
  it("offers the three, with the chosen one checked", () => {
    const onChange = vi.fn();
    render(<SendModePicker mode="steer" onChange={onChange} />);

    expect(screen.getByRole("radio", { name: "Adds to the task" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("radio", { name: "Asks on the side" }));
    expect(onChange).toHaveBeenCalledWith("aside");
  });

  it("lists the corrections on their way, and nothing when there are none", () => {
    const { rerender, container } = render(<WaitingSteers steers={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<WaitingSteers steers={[{ id: "s1", text: "use the EU numbers" }]} />);
    expect(screen.getByText("use the EU numbers")).toBeInTheDocument();
    expect(screen.getByText(/reads this at its next step/)).toBeInTheDocument();
  });

  it("shows each side question waiting, answered or refused, and lets it go", async () => {
    const onDismiss = vi.fn();
    const { container, rerender } = render(<SideAnswers asides={[]} onDismiss={onDismiss} />);
    expect(container).toBeEmptyDOMElement();

    rerender(
      <SideAnswers
        asides={[
          { id: "a", question: "how long?" },
          { id: "b", question: "the cost?", answer: "About **$0.02**." },
          { id: "c", question: "why?", error: "Over budget" },
        ]}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByText(/Answering beside the task/)).toBeInTheDocument();
    expect(await screen.findByText(/0\.02/)).toBeInTheDocument();
    expect(screen.getByText("Over budget")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[1]!);
    expect(onDismiss).toHaveBeenCalledWith("b");
  });
});
