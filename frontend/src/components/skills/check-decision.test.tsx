import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CheckDecision } from "./check-decision";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

function decide(check: SkillCheck) {
  const onApply = vi.fn();
  const onDiscard = vi.fn();
  render(<CheckDecision check={check} busy={false} onApply={onApply} onDiscard={onDiscard} />);
  return { onApply, onDiscard };
}

describe("CheckDecision", () => {
  it("applies a change that passed", async () => {
    const { onApply } = decide(finishedCheck());

    expect(screen.getByText("No agent got worse and at least one got better.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledWith({ acknowledge_unknown: false, pin_worse: false });
  });

  it("waits for agents that could not be checked to be acknowledged", async () => {
    const { onApply } = decide(
      finishedCheck({
        verdict: "needs_ack",
        agents: [checkAgent({ state: "better" }), checkAgent({ name: "C", state: "unknown" })],
      }),
    );

    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledWith({ acknowledge_unknown: true, pin_worse: false });
  });

  it("applies a change that made an agent worse only with that agent pinned", async () => {
    const { onApply } = decide(
      finishedCheck({
        verdict: "blocked",
        outcomes: ["improve_further", "apply_and_pin", "fork_for_helped", "discard"],
        warnings: ["within_noise"],
      }),
    );

    expect(screen.getByText(/the check saw a difference it could not confirm/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply, and keep the worse agents on their version" }),
    );

    expect(onApply).toHaveBeenCalledWith({ acknowledge_unknown: false, pin_worse: true });
  });

  it("says why a fork's change that made an agent worse can only be improved or discarded", async () => {
    const { onDiscard } = decide(
      finishedCheck({ verdict: "blocked", outcomes: ["improve_further", "discard"] }),
    );

    expect(screen.getByText(/This change is to a fork/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onDiscard).toHaveBeenCalled();
  });
});
