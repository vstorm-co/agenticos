import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DelegationModeField } from "./delegation-mode-field";
import type { DelegationMode } from "@/types/agents";

function mount(value: DelegationMode | null, disabled = false) {
  const onChange = vi.fn();
  render(<DelegationModeField id="mode" value={value} onChange={onChange} disabled={disabled} />);
  return onChange;
}

describe("DelegationModeField", () => {
  it("explains what following the policy means when nothing overrides it", () => {
    mount(null);

    expect(screen.getByRole("combobox", { name: "When it hands back" })).toHaveTextContent(
      "Follow the policy",
    );
    expect(screen.getByText(/changing it moves every delegate that never disagreed/)).toBeVisible();
  });

  it("explains the mode that is actually set, not the default one", () => {
    // Which is the point of the sentence: "async" is a real thing to want for one
    // slow specialist and a poor default, and the words are where that is said.
    mount("async");

    expect(screen.getByText(/keeps working and collects the answer later/)).toBeVisible();
  });

  it.each<[DelegationMode, string]>([
    ["sync", "Wait for it"],
    ["async", "Start it and carry on"],
    ["auto", "Let the model decide"],
  ])("stores %s when it is chosen", async (mode, label) => {
    const onChange = mount(null);

    await userEvent.click(screen.getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(screen.getByRole("option", { name: label }));

    expect(onChange).toHaveBeenCalledWith(mode);
  });

  it("stores following the policy as the absence of a mode", async () => {
    const onChange = mount("sync");

    await userEvent.click(screen.getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(screen.getByRole("option", { name: "Follow the policy" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("is inert for somebody who may not edit the agent", () => {
    mount("sync", true);

    expect(screen.getByRole("combobox", { name: "When it hands back" })).toBeDisabled();
  });
});
