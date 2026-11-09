import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillChecks } from "./skill-checks";
import { finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

const held = vi.hoisted(() => ({
  history: {
    checks: undefined as SkillCheck[] | undefined,
    total: 0,
    isLoading: false,
    error: null as Error | null,
  },
  opened: null as string | null,
  open: vi.fn(),
  close: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("@/hooks/use-skill-check", () => ({
  useSkillCheckHistory: () => held.history,
}));
vi.mock("@/hooks/use-url-state", () => ({
  useUrlOverlay: () => [held.opened, { open: held.open, close: held.close, replace: held.replace }],
}));
vi.mock("./skill-check-dialog", () => ({
  SkillCheckDialog: ({
    resume,
    onOpenChange,
    onEdit,
  }: {
    resume: string;
    onOpenChange: (open: boolean) => void;
    onEdit: (candidate: { description: string; content: string }) => void;
  }) => (
    <div role="dialog">
      {resume}
      <button onClick={() => onOpenChange(false)}>Close it</button>
      <button onClick={() => onEdit({ description: "D", content: "C" })}>Edit it</button>
    </div>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  held.history = { checks: [], total: 0, isLoading: false, error: null };
  held.opened = null;
});

describe("SkillChecks", () => {
  it("lists each check by the version it was written over, what it found and what was done", async () => {
    held.history = {
      checks: [
        finishedCheck({ id: "c-2", status: "discarded", verdict: "no_better", hidden: 1 }),
        finishedCheck({ id: "c-1", status: "running", verdict: null }),
      ],
      total: 2,
      isLoading: false,
      error: null,
    };
    render(<SkillChecks skillId="s-1" forkId={null} onEdit={vi.fn()} />);

    expect(screen.getByText("2 checks")).toBeInTheDocument();
    expect(screen.getByText("Over v3 · 2 agents")).toBeInTheDocument();
    expect(screen.getByText(/· Nobody better/)).toBeInTheDocument();
    expect(screen.getByText("Discarded")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Details" })[0]!);

    expect(held.open).toHaveBeenCalledWith("c-2");
  });

  it("opens the check the address names, and goes back to editing its text from there", async () => {
    held.opened = "c-9";
    const onEdit = vi.fn();
    render(<SkillChecks skillId="s-1" forkId="f-1" onEdit={onEdit} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("c-9");
    await userEvent.click(screen.getByRole("button", { name: "Edit it" }));
    expect(onEdit).toHaveBeenCalledWith({ description: "D", content: "C" });
    expect(held.replace).toHaveBeenCalledWith(null);
    await userEvent.click(screen.getByRole("button", { name: "Close it" }));
    expect(held.close).toHaveBeenCalled();
  });

  it("says when nothing was checked, while the list loads, and when it cannot be read", () => {
    const { rerender } = render(<SkillChecks skillId="s-1" forkId={null} onEdit={vi.fn()} />);
    expect(screen.getByText("No change to this line has been checked yet.")).toBeInTheDocument();

    held.history = { checks: undefined, total: 0, isLoading: true, error: null };
    rerender(<SkillChecks skillId="s-1" forkId={null} onEdit={vi.fn()} />);
    expect(screen.queryByText(/No change/)).toBeNull();

    held.history = { checks: undefined, total: 0, isLoading: false, error: new Error("Refused") };
    rerender(<SkillChecks skillId="s-1" forkId={null} onEdit={vi.fn()} />);
    expect(screen.getByText("Refused")).toBeInTheDocument();
  });
});
