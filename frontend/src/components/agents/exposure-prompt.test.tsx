import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExposurePrompt } from "./exposure-prompt";

/**
 * What a binding adds to the agent's instructions.
 *
 * The same published agent answers in a dashboard, on a widget and in a
 * Mattermost channel, and those want different things of it. Editing the spec to
 * suit one of them changes it on all the others.
 */
function mount(value: string | null = null, disabled = false) {
  const onSave = vi.fn();
  render(
    <ExposurePrompt botName="Acme Support" value={value} disabled={disabled} onSave={onSave} />,
  );
  return onSave;
}

describe("a binding's extra instructions", () => {
  it("opens with what is already saved", () => {
    mount("Answer in short paragraphs.");

    expect(screen.getByRole("textbox")).toHaveValue("Answer in short paragraphs.");
  });

  it("saves nothing until something changed", () => {
    mount("Answer in short paragraphs.");

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("saves what was typed", async () => {
    const onSave = mount();

    await userEvent.type(screen.getByRole("textbox"), "No headings here.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith("No headings here.");
  });

  it("clears with a null rather than an empty line", async () => {
    // The run appends what it finds, and a blank line appended to every prompt
    // is still an edit to every prompt.
    const onSave = mount("Answer in short paragraphs.");

    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(null);
  });

  it("treats whitespace as no change", async () => {
    const onSave = mount("Be terse.");

    await userEvent.type(screen.getByRole("textbox"), "   ");

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("waits while a save is in flight", () => {
    mount(null, true);

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("names the bot it belongs to", () => {
    // Every binding renders one of these, and they are identical otherwise.
    mount();

    expect(screen.getByLabelText("Extra instructions on Acme Support")).toBeVisible();
  });
});
