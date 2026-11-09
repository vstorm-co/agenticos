import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CheckDecision } from "./check-decision";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

vi.mock("@/hooks/use-skill-versions", () => ({
  useSkillAgents: () => ({
    agents: {
      items: [{ agent: { id: "agent-Online desk", slug: "desk" }, can_change: true }],
    },
    error: null,
    retry: vi.fn(),
    retrying: false,
  }),
}));

function decide(check: SkillCheck, onEdit?: () => void) {
  const onApply = vi.fn();
  const onDiscard = vi.fn();
  const onFork = vi.fn().mockResolvedValue(null);
  render(
    <CheckDecision
      check={check}
      busy={false}
      onApply={onApply}
      onFork={onFork}
      onDiscard={onDiscard}
      onEdit={onEdit}
    />,
  );
  return { onApply, onDiscard, onFork };
}

async function discard() {
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Discard" }),
  );
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
    await discard();
    expect(onDiscard).toHaveBeenCalled();
  });

  it("offers every way out the check returns when no agent got better", async () => {
    const onEdit = vi.fn();
    decide(
      finishedCheck({
        verdict: "no_better",
        outcomes: ["improve_further", "fork_for_helped", "discard"],
      }),
      onEdit,
    );

    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save as a fork…" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Back to editing" }));
    expect(onEdit).toHaveBeenCalled();
  });

  it("improves further in a new session when no editor holds the text", () => {
    decide(
      finishedCheck({
        verdict: "no_better",
        outcomes: ["improve_further", "discard"],
        line: { fork_id: "f-1", name: "Prints" },
      }),
    );

    expect(screen.getByRole("link", { name: "Improve further" })).toHaveAttribute(
      "href",
      "/skills/s-1/improve/new?fork=f-1",
    );
    expect(screen.queryByRole("button", { name: "Save as a fork…" })).toBeNull();
  });

  it("improves main further in a session on main", () => {
    decide(finishedCheck({ verdict: "no_better", outcomes: ["improve_further"] }));

    expect(screen.getByRole("link", { name: "Improve further" })).toHaveAttribute(
      "href",
      "/skills/s-1/improve/new",
    );
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
  });

  it("makes a fork for the agents picked, acknowledging the ones nobody could check", async () => {
    const { onFork } = decide(
      finishedCheck({
        verdict: "needs_ack",
        outcomes: ["apply", "improve_further", "fork_for_helped", "discard"],
        agents: [checkAgent({ state: "better" }), checkAgent({ name: "C", state: "unknown" })],
      }),
    );

    expect(screen.getByRole("button", { name: "Save as a fork…" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await userEvent.click(screen.getByRole("button", { name: "Make the fork and move 1 agent" }));

    expect(onFork).toHaveBeenCalledWith({
      name: "Online desk",
      agent_ids: ["agent-Online desk"],
      acknowledge_unknown: true,
    });
  });

  it("discards only once the person confirms it", async () => {
    const { onDiscard } = decide(finishedCheck());

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByText("Discard this change?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("holds improving further back while a decision is being made", () => {
    render(
      <CheckDecision
        check={finishedCheck({ verdict: "no_better", outcomes: ["improve_further"] })}
        busy
        onApply={vi.fn()}
        onFork={vi.fn()}
        onDiscard={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Improve further" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Improve further" })).toBeNull();
  });
});
