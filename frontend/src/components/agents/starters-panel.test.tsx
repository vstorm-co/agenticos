import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StartersPanel } from "./starters-panel";

function panel(starters: string[], disabled = false) {
  const onChange = vi.fn();
  render(<StartersPanel starters={starters} disabled={disabled} onChange={onChange} />);
  return onChange;
}

describe("StartersPanel", () => {
  it("adds a first message with the button or Enter", async () => {
    const onChange = panel(["What can you do?"]);
    const input = screen.getByRole("textbox", { name: "New first message" });

    await userEvent.type(input, "Summarise my week");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenLastCalledWith(["What can you do?", "Summarise my week"]);

    await userEvent.type(input, "Draft an email{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["What can you do?", "Draft an email"]);
  });

  it("will not add a blank one", async () => {
    const onChange = panel([]);

    await userEvent.type(screen.getByRole("textbox", { name: "New first message" }), "   {Enter}");

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("edits and removes one in place", async () => {
    const onChange = panel(["One", "Two"]);

    await userEvent.type(screen.getByRole("textbox", { name: "First message 2" }), "!");
    expect(onChange).toHaveBeenLastCalledWith(["One", "Two!"]);

    await userEvent.click(screen.getByRole("button", { name: "Remove first message 1" }));
    expect(onChange).toHaveBeenLastCalledWith(["Two"]);
  });

  it("offers no fifth", () => {
    panel(["1", "2", "3", "4"]);

    expect(screen.queryByRole("textbox", { name: "New first message" })).toBeNull();
  });

  it("is read-only for somebody who may not edit the agent", () => {
    panel(["One"], true);

    expect(screen.getByRole("textbox", { name: "First message 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove first message 1" })).toBeDisabled();
  });
});
