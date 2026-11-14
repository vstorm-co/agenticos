import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckRunning } from "./check-running";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

const held = vi.hoisted(() => ({
  open: null as SkillCheck | null,
  error: null as unknown,
  refetch: (() => {}) as () => void,
}));
vi.mock("@/hooks/use-skill-check", () => ({
  useOpenSkillCheck: () => ({ check: held.open, error: held.error, refetch: held.refetch }),
}));
vi.mock("./skill-check-dialog", () => ({
  SkillCheckDialog: ({
    resume,
    onEdit,
  }: {
    resume: string;
    onEdit: (candidate: { description: string; content: string }) => void;
  }) => (
    <div role="dialog">
      {resume}
      <button onClick={() => onEdit({ description: "D", content: "C" })}>Edit it</button>
    </div>
  ),
}));

beforeEach(() => {
  held.open = null;
  held.error = null;
  held.refetch = vi.fn();
});

describe("CheckRunning", () => {
  it("says the line's checks could not be read rather than drawing nothing, and reads them again", async () => {
    held.error = new Error("checks offline");
    render(<CheckRunning skillId="s-1" forkId={null} onEdit={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Whether a check of this line is still running or waiting for you could not be read: checks offline",
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(held.refetch).toHaveBeenCalled();
  });

  it("keeps showing a check it already read when reading it again fails", () => {
    held.open = finishedCheck({ agents: [checkAgent({ name: "Online desk", state: "better" })] });
    held.error = new Error("checks offline");
    render(<CheckRunning skillId="s-1" forkId={null} onEdit={vi.fn()} />);

    expect(screen.getByText(/waits for your decision/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("draws nothing while no check waits on the line", () => {
    const { container } = render(<CheckRunning skillId="s-1" forkId={null} onEdit={vi.fn()} />);
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
    const onEdit = vi.fn();
    render(<CheckRunning skillId="s-1" forkId={null} onEdit={onEdit} />);

    expect(screen.getByText("Check running: 1 of 2 agents checked.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("c-7");
    await userEvent.click(screen.getByRole("button", { name: "Edit it" }));
    expect(onEdit).toHaveBeenCalledWith({ description: "D", content: "C" });
  });

  it("says a finished check waits for a decision", () => {
    held.open = finishedCheck({ agents: [checkAgent({ name: "Online desk", state: "better" })] });
    render(<CheckRunning skillId="s-1" forkId="f-1" onEdit={vi.fn()} />);

    expect(
      screen.getByText("A check finished on 1 agent and waits for your decision."),
    ).toBeInTheDocument();
  });
});
