import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Skill } from "@/types/providers";
import { SkillPageHeader, type Merges } from "./skill-page-header";

const state = vi.hoisted(() => ({ runsView: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.runsView, isLoading: false }),
}));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({ actions }: { actions: ReactNode }) => <div>{actions}</div>,
}));

const SKILL = { id: "k1", name: "refunds", version: 7, can_edit: true } as Skill;
const MERGES = {
  fork: "returns",
  catchUp: "/skills/k1/improve/new?fork=f1&merge=catch_up",
  toMain: "/skills/k1/improve/new?fork=f1&merge=to_main",
};

function mount(skill: Skill = SKILL, merges: Merges | null = MERGES) {
  render(
    <SkillPageHeader
      skill={skill}
      line="returns"
      improveHref="/skills/k1/improve/new?fork=f1"
      merges={merges}
      onEdit={vi.fn()}
      onFork={null}
    />,
  );
}

/** Open a fork's More menu, where its rare actions wait. */
async function more() {
  await userEvent.click(screen.getByRole("button", { name: "More actions" }));
}

beforeEach(() => {
  state.runsView = true;
});

describe("SkillPageHeader", () => {
  it("offers catching the fork shown up on the bar, and moving it to main under More", async () => {
    mount();

    expect(screen.getByRole("link", { name: "Catch “returns” up with main" })).toHaveAttribute(
      "href",
      MERGES.catchUp,
    );
    expect(screen.queryByRole("link", { name: "Move “returns” to main" })).toBeNull();
    await more();
    expect(screen.getByRole("menuitem", { name: "Move “returns” to main" })).toHaveAttribute(
      "href",
      MERGES.toMain,
    );
  });

  it("offers only what the fork has to merge, and nothing to a reader", async () => {
    mount(SKILL, { ...MERGES, catchUp: null });
    expect(screen.queryByRole("link", { name: /up with main/ })).not.toBeInTheDocument();
    await more();
    expect(screen.getByRole("menuitem", { name: "Move “returns” to main" })).toBeVisible();

    cleanup();
    mount({ ...SKILL, can_edit: false });
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
  });

  it("holds both merges of a fork with nothing of its own, and says why", async () => {
    mount(SKILL, { fork: "returns", catchUp: null, toMain: null, empty: true });
    const button = screen.getByRole("button", { name: "Catch “returns” up with main" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      "Make a change in the fork first; there's nothing to merge yet.",
    );
    await more();
    const toMain = screen.getByRole("menuitem", { name: "Move “returns” to main" });
    expect(toMain).toHaveAttribute("aria-disabled", "true");
    expect(toMain).toHaveAttribute(
      "title",
      "Make a change in the fork first; there's nothing to merge yet.",
    );
    expect(screen.queryByRole("link", { name: /main/ })).not.toBeInTheDocument();
  });

  it("offers returning a fork with nothing of its own to main", async () => {
    const open = vi.fn();
    render(
      <SkillPageHeader
        skill={SKILL}
        line="returns"
        improveHref="/skills/k1/improve/new?fork=f1"
        onReturn={{ fork: "returns", open }}
        onEdit={vi.fn()}
        onFork={null}
      />,
    );

    await more();
    await userEvent.click(screen.getByRole("menuitem", { name: "Return “returns” to main" }));
    expect(open).toHaveBeenCalledOnce();
  });

  it("offers returning an empty fork to a reader who may not read runs", async () => {
    state.runsView = false;
    render(
      <SkillPageHeader
        skill={SKILL}
        line="returns"
        improveHref="/skills/k1/improve/new?fork=f1"
        merges={{ fork: "returns", catchUp: null, toMain: null, empty: true }}
        onReturn={{ fork: "returns", open: vi.fn() }}
        onEdit={vi.fn()}
        onFork={null}
      />,
    );

    await more();
    expect(screen.getByRole("menuitem", { name: "Return “returns” to main" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: "Move “returns” to main" })).toBeNull();
  });

  it("offers deleting the skill beside Edit to an editor", async () => {
    const onDelete = vi.fn();
    render(
      <SkillPageHeader
        skill={SKILL}
        line={null}
        improveHref="/skills/k1/improve/new"
        onEdit={vi.fn()}
        onFork={null}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("keeps a fork's new fork and delete under More", async () => {
    const onDelete = vi.fn();
    const onFork = vi.fn();
    render(
      <SkillPageHeader
        skill={SKILL}
        line="returns"
        improveHref="/skills/k1/improve/new?fork=f1"
        onEdit={vi.fn()}
        onFork={onFork}
        onDelete={onDelete}
      />,
    );
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New fork" })).toBeNull();

    await more();
    await userEvent.click(screen.getByRole("menuitem", { name: "New fork" }));
    expect(onFork).toHaveBeenCalled();
    await more();
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalled();
  });
});
