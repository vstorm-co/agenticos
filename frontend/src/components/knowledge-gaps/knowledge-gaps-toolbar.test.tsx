import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import { KnowledgeGapsToolbar } from "./knowledge-gaps-toolbar";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  regroup: vi.fn(),
  regroupedFor: [] as string[],
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useRegroupKnowledgeGaps: (id: string) => {
    state.regroupedFor.push(id);
    return { mutate: state.regroup, isPending: false };
  },
}));

describe("KnowledgeGapsToolbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [];
    state.regroupedFor = [];
  });

  it("offers grouping now on a collection to a caller who edits it", async () => {
    state.granted = [Perm.collectionsEdit];
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "collection", id: "kb1" }}
        status="open"
        onStatus={vi.fn()}
      />,
    );
    expect(screen.getByText(/searched this knowledge base for/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Group now" }));
    expect(state.regroupedFor).toContain("kb1");
    expect(state.regroup).toHaveBeenCalled();
  });

  it("does not offer it to a caller who only reads the collection", () => {
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "collection", id: "kb1" }}
        status="open"
        onStatus={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Group now" })).toBeNull();
  });

  it("does not offer it on an agent's list, which spans knowledge bases", () => {
    state.granted = [Perm.collectionsEdit];
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "agent", id: "a1" }}
        status="dismissed"
        onStatus={vi.fn()}
      />,
    );
    expect(screen.getByText(/this agent searched its knowledge bases/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Group now" })).toBeNull();
  });

  it("hands the status picked back to the list", async () => {
    const onStatus = vi.fn();
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "agent", id: "a1" }}
        status="dismissed"
        onStatus={onStatus}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Show topics" }));
    await userEvent.click(screen.getByRole("option", { name: "Open" }));
    expect(onStatus).toHaveBeenCalledWith("open");
  });
});
