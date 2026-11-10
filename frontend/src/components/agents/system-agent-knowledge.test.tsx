import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SystemAgentKnowledge } from "./system-agent-knowledge";
import type { SystemAgentKind } from "@/types/agents";

function mount({
  kind = "judge" as SystemAgentKind,
  maxSteps = undefined as number | null | undefined,
  disabled = false,
} = {}) {
  const onMaxSteps = vi.fn();
  render(<SystemAgentKnowledge search={{ kind, maxSteps, onMaxSteps }} disabled={disabled} />);
  return { onMaxSteps };
}

const steps = () => screen.getByRole("spinbutton", { name: "Max steps" }) as HTMLInputElement;

describe("how a system agent searches a knowledge base", () => {
  it.each([
    ["judge", /against the knowledge bases of the agent it grades/],
    ["generator", /the knowledge bases you draft cases from/],
    ["classifier", /already answers a question before calling it a gap/],
    ["drafter", /Searches the gap's knowledge base/],
    ["improver", /the knowledge bases of the agent it improves/],
  ] as const)("says what a search gives a %s", (kind, sentence) => {
    mount({ kind });

    expect(screen.getByText(sentence)).toBeInTheDocument();
  });

  it("offers no collection to pick and no switch of its own", () => {
    mount();

    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("offers the steps a search takes, with the runner's own default in the empty box", () => {
    mount();

    expect(steps().value).toBe("");
    expect(steps()).toHaveAttribute("placeholder", "3");
    expect(steps()).toHaveAttribute("min", "1");
    expect(steps()).toHaveAttribute("max", "5");
    expect(steps()).toHaveAccessibleDescription(
      "Each step is a paid request on every answer it reads. At most 5; left empty, 3.",
    );
  });

  it("writes a step count, and clears it back to unset", () => {
    const { onMaxSteps } = mount({ maxSteps: 4 });

    expect(steps().value).toBe("4");
    fireEvent.change(steps(), { target: { value: "2" } });
    expect(onMaxSteps).toHaveBeenLastCalledWith(2);
    fireEvent.change(steps(), { target: { value: "" } });
    expect(onMaxSteps).toHaveBeenLastCalledWith(null);
  });

  it("takes nothing while disabled", () => {
    mount({ maxSteps: 2, disabled: true });

    expect(steps()).toBeDisabled();
  });
});
