import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SystemAgentKnowledge } from "./system-agent-knowledge";
import { withCapability } from "@/lib/agent-spec";
import type { SystemAgentKind } from "@/types/agents";

function mount({
  kind = "judge" as SystemAgentKind,
  on = false,
  maxSteps = undefined as number | null | undefined,
  disabled = false,
} = {}) {
  const onToggle = vi.fn();
  const onMaxSteps = vi.fn();
  const capabilities = withCapability(withCapability([], "thinking", true), "knowledge", on);
  render(
    <SystemAgentKnowledge
      kind={kind}
      capabilities={capabilities}
      maxSteps={maxSteps}
      onToggle={onToggle}
      onMaxSteps={onMaxSteps}
      disabled={disabled}
    />,
  );
  return { onToggle, onMaxSteps };
}

const steps = () => screen.queryByRole("spinbutton", { name: "Max steps" });

describe("a system agent's knowledge base search", () => {
  it.each([
    ["judge", /against the knowledge bases of the agent it grades/],
    ["generator", /the knowledge bases you draft cases from/],
    ["classifier", /already answers a question before calling it a gap/],
    ["drafter", /Searches the gap's knowledge base/],
    ["improver", /the knowledge bases of the agent it improves/],
  ] as const)("says what it gives a %s", (kind, sentence) => {
    mount({ kind });

    expect(screen.getByText(sentence)).toBeInTheDocument();
  });

  it("asks to switch the search on, and offers no collection to pick", async () => {
    const { onToggle } = mount();

    expect(screen.getByRole("switch", { name: "Use the knowledge base" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("switch", { name: "Use the knowledge base" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("shows how many steps a search may take only while it is on", () => {
    mount();
    expect(steps()).toBeNull();
  });

  it("offers the steps a search takes, with the runner's own default in the empty box", () => {
    mount({ on: true });

    expect(screen.getByRole("switch", { name: "Use the knowledge base" })).toBeChecked();
    const field = steps() as HTMLInputElement;
    expect(field.value).toBe("");
    expect(field).toHaveAttribute("placeholder", "3");
    expect(field).toHaveAttribute("max", "5");
    expect(field).toHaveAccessibleDescription(
      "Each step is a paid request on every answer it reads. At most 5; left empty, 3.",
    );
  });

  it("writes a step count, and clears it back to unset", () => {
    const { onMaxSteps } = mount({ on: true, maxSteps: 4 });

    expect((steps() as HTMLInputElement).value).toBe("4");
    fireEvent.change(steps() as HTMLElement, { target: { value: "2" } });
    expect(onMaxSteps).toHaveBeenLastCalledWith(2);
    fireEvent.change(steps() as HTMLElement, { target: { value: "" } });
    expect(onMaxSteps).toHaveBeenLastCalledWith(null);
  });

  it("takes nothing from somebody who may not change the agent", async () => {
    const { onToggle } = mount({ on: true, disabled: true });

    expect(screen.getByRole("switch", { name: "Use the knowledge base" })).toBeDisabled();
    expect(steps()).toBeDisabled();
    await userEvent.click(screen.getByRole("switch", { name: "Use the knowledge base" }));
    expect(onToggle).not.toHaveBeenCalled();
  });
});
