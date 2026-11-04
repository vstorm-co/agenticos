import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckRunning } from "./check-running";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

const held = vi.hoisted(() => ({ open: null as SkillCheck | null }));
vi.mock("@/hooks/use-skill-check", () => ({
  useOpenSkillCheck: () => held.open,
}));
vi.mock("./skill-check-dialog", () => ({
  SkillCheckDialog: ({ resume }: { resume: string }) => <div role="dialog">{resume}</div>,
}));

beforeEach(() => {
  held.open = null;
});

describe("CheckRunning", () => {
  it("draws nothing while no check waits on the line", () => {
    const { container } = render(<CheckRunning skillId="s-1" forkId={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says how far a running check is, and opens it again on Show", async () => {
    held.open = finishedCheck({
      id: "c-7",
      status: "running",
      agents: [
        checkAgent({ name: "Online desk", state: "better" }),
        checkAgent({ name: "Gift shop", state: "running" }),
      ],
    });
    render(<CheckRunning skillId="s-1" forkId={null} />);

    expect(screen.getByText("Check running: 1 of 2 agents checked.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("c-7");
  });

  it("says a finished check waits for a decision", () => {
    held.open = finishedCheck({ agents: [checkAgent({ name: "Online desk", state: "better" })] });
    render(<CheckRunning skillId="s-1" forkId="f-1" />);

    expect(
      screen.getByText("A check finished on 1 agent and waits for your decision."),
    ).toBeInTheDocument();
  });
});
