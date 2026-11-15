import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { Skill } from "@/types/providers";
import type { SkillAgentList, SkillAgentUsage } from "@/types/skill-versions";
import { DeleteSkillDialog } from "./delete-skill-dialog";

const SKILL = { id: "s1", name: "returns-policy" } as Skill;

const row = (name: string, via: string | null = null, canChange = true) =>
  ({
    agent: { id: name, name, slug: name },
    via_specialist: via,
    can_change: canChange,
  }) as SkillAgentUsage;

function open(
  agents: SkillAgentList | undefined,
  onDelete = vi.fn().mockResolvedValue(undefined),
  agentsError: unknown = null,
) {
  const onClose = vi.fn();
  render(
    <DeleteSkillDialog
      skill={SKILL}
      agents={agents}
      agentsError={agentsError}
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
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("counts agents it cannot name", () => {
    open(list([], 1));
    expect(screen.getByRole("alert")).toHaveTextContent("Used by 1 agent you can't see.");
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
    open(list([]), onDelete);

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

    expect(await screen.findByRole("alert")).toHaveTextContent("Used by 3 agents you can't see.");
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

  it("offers no delete while it is still finding out who uses the skill", () => {
    open(undefined);
    expect(screen.getByRole("status")).toHaveTextContent("Checking which agents use it");
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("still offers a delete the server guards when the agents could not be read", async () => {
    const { onDelete } = open(undefined, vi.fn().mockResolvedValue(undefined), new Error("down"));
    expect(screen.getByText(/could not be read/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("takes a used skill off its agents and deletes it, once confirmed", async () => {
    const { onDelete } = open(list([row("Desk"), row("Desk", "refunds"), row("Counter")]));

    await userEvent.click(screen.getByRole("button", { name: "Remove from 2 agents and delete" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText(/taken out of these 2 agents' drafts/)).toHaveTextContent(
      /a new version without it is published.*test questions, if it has them, stay in Datasets/,
    );
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Desk",
      "Counter",
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Used by 2 agents: Desk and Counter.");
    await userEvent.click(screen.getByRole("button", { name: "Remove from 2 agents and delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and delete" }));
    expect(onDelete).toHaveBeenCalledWith(true);
  });

  it("names the agents the reader may not change, and offers no removal", () => {
    open(list([row("Desk"), row("Counter", null, false)]));

    expect(screen.getByText(/You may not change Counter/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /and delete/ })).toBeNull();
  });

  it("offers no removal while some agents are hidden from the reader", () => {
    open(list([row("Desk")], 1));

    expect(screen.getByText(/Some of them you cannot see/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /and delete/ })).toBeNull();
  });

  it("names whom the server would not let the removal change", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(409, "In use", {
        error: {
          code: "IN_USE",
          message: "In use",
          details: {
            agents: [{ id: "a1", name: "Desk" }],
            not_editable: [{ id: "a1", name: "Desk" }],
          },
        },
      }),
    );
    open(list([row("Desk")]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Remove from 1 agent and delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and delete" }));

    expect(await screen.findByText(/You may not change Desk/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /and delete/ })).toBeNull();
  });

  it("names the environments still waiting for promotion with the skill", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(409, "In use", {
        error: {
          code: "IN_USE",
          message: "In use",
          details: {
            agents: [{ id: "a1", name: "Desk" }],
            hidden: 0,
            not_editable: [],
            waiting: [{ id: "a1", name: "Desk", environments: ["staging", "prod"] }],
          },
        },
      }),
    );
    open(list([row("Desk")]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Remove from 1 agent and delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and delete" }));

    expect(
      await screen.findByText(/Desk still serves it in staging and prod, which wait for promotion/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /and delete/ })).toBeNull();
  });

  it("asks to try again when an agent took the skill up meanwhile", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(409, "Changed", {
        error: { code: "IN_USE", message: "Changed", details: { reason: "agents_changed" } },
      }),
    );
    open(list([row("Desk")]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Remove from 1 agent and delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and delete" }));

    expect(await screen.findByText(/started using the skill.*Try again/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove from 1 agent and delete" })).toBeVisible();
  });

  it("sends the person to the agent whose spec does not publish without the skill", async () => {
    const onDelete = vi.fn().mockRejectedValue(
      new ApiError(400, "Invalid", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid",
          details: { agent_id: "a1", agent_name: "Desk", problems: ["model removed"] },
        },
      }),
    );
    open(list([row("Desk")]), onDelete);

    await userEvent.click(screen.getByRole("button", { name: "Remove from 1 agent and delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and delete" }));

    expect(await screen.findByRole("link", { name: "Fix it in the Builder" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
    expect(screen.getByText(/Desk's newest spec does not publish/)).toBeInTheDocument();
  });
});
