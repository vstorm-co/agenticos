import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { Skill } from "@/types/providers";
import type { SkillAgentList, SkillAgentUsage } from "@/types/skill-versions";
import { DeleteSkillDialog } from "./delete-skill-dialog";

const SKILL = { id: "s1", name: "returns-policy" } as Skill;

const row = (name: string, via: string | null = null) =>
  ({ agent: { id: name, name, slug: name }, via_specialist: via }) as SkillAgentUsage;

function open(agents: SkillAgentList | undefined, onDelete = vi.fn().mockResolvedValue(undefined)) {
  const onClose = vi.fn();
  render(
    <DeleteSkillDialog
      skill={SKILL}
      agents={agents}
      deleting={false}
      onDelete={onDelete}
      onClose={onClose}
    />,
  );
  return { onDelete, onClose };
}

const list = (items: SkillAgentUsage[], hidden = 0) =>
  ({ main_latest: { id: "m5", number: 5 }, items, hidden }) as SkillAgentList;

describe("DeleteSkillDialog", () => {
  it("offers no delete for a skill agents use, and names them", async () => {
    const { onClose } = open(list([row("Desk"), row("Desk", "refunds"), row("Counter")], 2));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Used by 4 agents: Desk and Counter, and 2 you can't see.",
    );
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("counts agents it cannot name", () => {
    open(list([], 1));
    expect(screen.getByRole("alert")).toHaveTextContent("Used by 1 agent, and 1 you can't see.");
  });

  it("deletes a skill nobody uses", async () => {
    const { onDelete } = open(list([]));

    expect(screen.getByText(/No agent uses it now/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("names the agents the server says bound it meanwhile", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(409, "In use", {
        error: {
          code: "IN_USE",
          message: "In use",
          details: { agents: [{ id: "a1", name: "Desk" }, "junk"] },
        },
      }),
    );
    open(undefined, onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Used by 1 agent: Desk.");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("reads a refusal without agents as nobody it can name", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(409, "In use", {
        error: { code: "IN_USE", message: "In use", details: { hidden: 3 } },
      }),
    );
    open(list([]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Used by 3 agents, and 3 you can't see.",
    );
  });

  it("says why any other delete failed", async () => {
    const onDelete = vi.fn().mockRejectedValue(new Error("Network down"));
    open(list([]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
  });

  it("closes on Escape", async () => {
    const { onClose } = open(list([]));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
