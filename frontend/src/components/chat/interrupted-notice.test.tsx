import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InterruptedNotice } from "./interrupted-notice";

describe("InterruptedNotice", () => {
  it("draws nothing with nothing on its way", () => {
    const { container } = render(<InterruptedNotice interrupted={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [{ interrupted: true }, /connection dropped mid-answer/],
    [{ interrupted: false, detached: true }, /earlier answer is still being written/],
    [{ interrupted: false, left: true }, /still answering when you left/],
  ])("says which answer is coming and why (%o)", (props, words) => {
    render(<InterruptedNotice {...props} />);
    expect(screen.getByRole("status")).toHaveTextContent(words);
  });

  it("re-reads the transcript when asked", async () => {
    const onRecheck = vi.fn();
    render(<InterruptedNotice interrupted={false} left onRecheck={onRecheck} />);

    await userEvent.click(screen.getByRole("button", { name: "Check for it" }));

    expect(onRecheck).toHaveBeenCalled();
  });

  it("says a lost answer is not coming, over anything else, and offers to ask again", async () => {
    const onAskAgain = vi.fn();
    render(
      <InterruptedNotice
        interrupted={false}
        left
        lost
        onRecheck={vi.fn()}
        onAskAgain={onAskAgain}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/stopped before it answered/);
    expect(screen.queryByRole("button", { name: "Check for it" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Ask again" }));
    expect(onAskAgain).toHaveBeenCalled();
  });

  it("says so without a button when there is nothing to ask again with", () => {
    render(<InterruptedNotice interrupted={false} lost />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
