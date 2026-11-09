import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Skill } from "@/types/providers";
import { SkillPageHeader, type Merges } from "./skill-page-header";

const ai = vi.hoisted(() => ({ enabled: true as boolean | null }));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => ({ orgId: "o1", enabled: ai.enabled }),
}));
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
  ai.enabled = true;
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

  it("holds Improve and Catch up while AI assistance is off, and says why", () => {
    ai.enabled = false;
    mount();

    for (const name of ["Improve fork “returns”", "Catch “returns” up with main"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).toHaveAccessibleDescription(/AI assistance is switched off/);
    }
    expect(screen.queryByRole("link", { name: /Improve|up with main/ })).toBeNull();
  });

  it("holds main's Improve too while AI assistance is off", () => {
    ai.enabled = false;
    render(
      <SkillPageHeader
        skill={SKILL}
        line={null}
        improveHref="/skills/k1/improve/new"
        onEdit={vi.fn()}
        onFork={null}
      />,
    );
    expect(screen.getByRole("button", { name: "Improve" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
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
