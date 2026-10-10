import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PromptVariablesPanel } from "./prompt-variables-panel";

const SYSTEM = [{ name: "user_name", description: "Who", example: "Ada" }];

function mount(overrides: Partial<Parameters<typeof PromptVariablesPanel>[0]> = {}) {
  const props = {
    system: SYSTEM,
    custom: [{ name: "policy", value: "v2", description: "Policy version" }],
    timeZone: "system",
    disabled: false,
    onInsert: vi.fn(),
    onCustomChange: vi.fn(),
    onTimeZoneChange: vi.fn(),
    ...overrides,
  };
  render(<PromptVariablesPanel {...props} />);
  return props;
}

describe("PromptVariablesPanel", () => {
  it("shows a custom variable without a description as plainly as one with", () => {
    mount({ custom: [{ name: "plain", value: "x" }] });

    expect(screen.getByRole("button", { name: "{{plain}}" })).toHaveAttribute("title", "");
  });

  it("inserts a variable when its chip is clicked", async () => {
    const props = mount();

    await userEvent.click(screen.getByRole("button", { name: "{{user_name}}" }));
    await userEvent.click(screen.getByRole("button", { name: "{{policy}}" }));

    expect(props.onInsert).toHaveBeenNthCalledWith(1, "user_name");
    expect(props.onInsert).toHaveBeenNthCalledWith(2, "policy");
  });

  it("adds, edits and removes custom variables", async () => {
    const props = mount();

    await userEvent.type(screen.getByLabelText("Name"), "support_email");
    await userEvent.type(screen.getByLabelText("Value"), "help@acme.com");
    await userEvent.click(screen.getByRole("button", { name: /Add variable/ }));
    expect(props.onCustomChange).toHaveBeenLastCalledWith([
      { name: "policy", value: "v2", description: "Policy version" },
      { name: "support_email", value: "help@acme.com" },
    ]);

    fireEvent.change(screen.getByLabelText("Value of policy"), { target: { value: "v3" } });
    expect(props.onCustomChange).toHaveBeenLastCalledWith([
      { name: "policy", value: "v3", description: "Policy version" },
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Remove policy" }));
    expect(props.onCustomChange).toHaveBeenLastCalledWith([]);
  });

  it("edits one custom variable and leaves the others as they were", () => {
    const props = mount({
      custom: [
        { name: "policy", value: "v2" },
        { name: "brand", value: "Acme" },
      ],
    });

    fireEvent.change(screen.getByLabelText("Value of brand"), { target: { value: "Globex" } });

    expect(props.onCustomChange).toHaveBeenLastCalledWith([
      { name: "policy", value: "v2" },
      { name: "brand", value: "Globex" },
    ]);
  });

  it("refuses a malformed or taken name before it is added", async () => {
    mount();

    await userEvent.type(screen.getByLabelText("Name"), "Bad Name");
    expect(screen.getByText(/Lower-case letters/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "user_name");
    expect(screen.getByText("That name is already a variable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add variable/ })).toBeDisabled();
  });

  it("tells the time in the deployment's zone, each person's, or a chosen one", () => {
    const props = mount();

    fireEvent.change(screen.getByLabelText("Time is told in"), { target: { value: "user" } });
    fireEvent.change(screen.getByLabelText("Time is told in"), { target: { value: "chosen" } });

    expect(props.onTimeZoneChange).toHaveBeenNthCalledWith(1, "user");
    expect(props.onTimeZoneChange).toHaveBeenNthCalledWith(2, "UTC");
  });

  it("edits a chosen zone by name", () => {
    const props = mount({ timeZone: "Europe/Warsaw" });

    fireEvent.change(screen.getByLabelText("A time zone I choose"), {
      target: { value: "Europe/Berlin" },
    });

    expect(props.onTimeZoneChange).toHaveBeenCalledWith("Europe/Berlin");
  });
});
