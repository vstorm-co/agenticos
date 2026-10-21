import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeGapsToolbar } from "./knowledge-gaps-toolbar";

const state = vi.hoisted(() => ({
  regroup: vi.fn(),
  regroupedFor: [] as string[],
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
    state.regroupedFor = [];
  });

  it("offers grouping now on a collection the server says the caller may change", async () => {
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "collection", id: "kb1" }}
        canRegroup
        status="open"
        onStatus={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Group now" }));
    expect(state.regroupedFor).toContain("kb1");
    expect(state.regroup).toHaveBeenCalled();
  });

  it("does not offer it to a caller who only reads the collection", () => {
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "collection", id: "kb1" }}
        canRegroup={false}
        status="open"
        onStatus={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Group now" })).toBeNull();
  });

  it("does not offer it on an agent's list, which spans knowledge bases", () => {
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "agent", id: "a1" }}
        canRegroup
        status="dismissed"
        onStatus={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Group now" })).toBeNull();
  });

  it("hands the status picked back to the list", async () => {
    const onStatus = vi.fn();
    render(
      <KnowledgeGapsToolbar
        scope={{ kind: "agent", id: "a1" }}
        canRegroup={false}
        status="dismissed"
        onStatus={onStatus}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Show topics" }));
    await userEvent.click(screen.getByRole("option", { name: "Open" }));
    expect(onStatus).toHaveBeenCalledWith("open");
  });
});
