import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { SkillFork } from "@/types/skill-versions";
import { ReturnForkDialog } from "./return-fork-dialog";

const returning = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
vi.mock("@/hooks/use-skill-merge", () => ({ useReturnForkToMain: () => returning }));

const FORK = { id: "f1", name: "returns", agents: 2, latest: null } as unknown as SkillFork;

beforeEach(() => {
  vi.clearAllMocks();
  returning.mutateAsync.mockResolvedValue({
    agents: [
      { agent: { id: "a1", name: "Desk" }, published: true, agent_version: 4, refused: null },
    ],
    hidden: 0,
    remaining: 1,
    archived: false,
  });
});

describe("ReturnForkDialog", () => {
  it("returns the fork's agents and says what it did before closing", async () => {
    const closed = vi.fn();
    render(<ReturnForkDialog skillId="k1" fork={FORK} onClose={closed} />);
    expect(
      screen.getByText(/The 2 agents reading this fork move to main's newest version/),
    ).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Return to main" }));

    expect(returning.mutateAsync).toHaveBeenCalledOnce();
    expect(await screen.findByText("Moved to main and published: Desk.")).toBeVisible();
    expect(closed).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(closed).toHaveBeenCalledOnce();
  });

  it("says why the return was refused, and closes when cancelled", async () => {
    returning.mutateAsync.mockRejectedValue(new ApiError(404, "Fork not found"));
    const closed = vi.fn();
    render(<ReturnForkDialog skillId="k1" fork={FORK} onClose={closed} />);

    await userEvent.click(screen.getByRole("button", { name: "Return to main" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fork not found");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(closed).toHaveBeenCalled();
  });
});
