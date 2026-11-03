import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Skill } from "@/types/providers";
import { SkillPageHeader } from "./skill-page-header";

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

function mount(
  skill: Skill = SKILL,
  merges: { fork: string; catchUp: string | null; toMain: string | null } | null = MERGES,
) {
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

beforeEach(() => {
  state.runsView = true;
});

describe("SkillPageHeader", () => {
  it("offers catching the fork shown up with main and moving it to main", () => {
    mount();

    expect(screen.getByRole("link", { name: "Catch “returns” up with main" })).toHaveAttribute(
      "href",
      MERGES.catchUp,
    );
    expect(screen.getByRole("link", { name: "Move “returns” to main" })).toHaveAttribute(
      "href",
      MERGES.toMain,
    );
  });

  it("offers only what the fork has to merge, and nothing to a reader", () => {
    mount(SKILL, { ...MERGES, catchUp: null });
    expect(screen.queryByRole("link", { name: /up with main/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Move “returns” to main" })).toBeVisible();

    document.body.innerHTML = "";
    mount({ ...SKILL, can_edit: false });
    expect(screen.queryByRole("link", { name: /to main/ })).not.toBeInTheDocument();
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

    await userEvent.click(screen.getByRole("button", { name: "Return “returns” to main" }));
    expect(open).toHaveBeenCalledOnce();
  });
});
