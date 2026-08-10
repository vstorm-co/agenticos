import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExposurePrompt } from "./exposure-prompt";
import type { ExposureVariable } from "@/types/exposures";

/**
 * What a binding adds to the agent's instructions.
 *
 * The same published agent answers in a dashboard, on a widget and in a
 * Mattermost channel, and those want different things of it. Editing the spec to
 * suit one of them changes it on all the others.
 */
function mount(value: string | null = null, disabled = false, variables: ExposureVariable[] = []) {
  const onSave = vi.fn();
  render(
    <ExposurePrompt
      botName="Acme Support"
      value={value}
      variables={variables}
      disabled={disabled}
      onSave={onSave}
    />,
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

describe("the placeholders a prompt may carry", () => {
  const variables: ExposureVariable[] = [
    { name: "channel_name", description: "The channel's name, as people see it" },
    { name: "member_list", description: "Who is in it, by name" },
  ];

  it("offers only what this platform can fill in", () => {
    mount(null, false, variables);

    expect(screen.getByRole("button", { name: "{channel_name}" })).toBeVisible();
    expect(screen.getByRole("button", { name: "{member_list}" })).toBeVisible();
  });

  it("says nothing at all where the platform fills in nothing", () => {
    mount(null, false, []);

    expect(screen.queryByText("Insert:")).toBeNull();
  });

  it("writes the placeholder where the caret is, not at the end", async () => {
    // The alternative is remembering an exact spelling that fails silently: an
    // unknown brace is left as written, on purpose, so a prompt quoting JSON
    // still works.
    const onSave = mount("Answer here.", false, variables);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    box.setSelectionRange(7, 7);

    await userEvent.click(screen.getByRole("button", { name: "{channel_name}" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith("Answer {channel_name}here.");
  });
});
