import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeGapDraft } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftCard } from "./knowledge-gap-draft-card";

const state = vi.hoisted(() => ({
  saved: [] as { blob: Blob; name: string }[],
  perms: new Set<string>(),
  drafters: [] as { id: string; system_key: string | null; can_edit: boolean }[],
  enabled: [] as boolean[],
}));
vi.mock("@/lib/file-access", () => ({
  saveBlob: (blob: Blob, name: string) => state.saved.push({ blob, name }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.perms.has(perm) }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: (_kind: string, { enabled }: { enabled: boolean }) => {
    state.enabled.push(enabled);
    return { agents: enabled ? state.drafters : [] };
  },
}));

const DRAFT: KnowledgeGapDraft = {
  title: "Parental leave",
  content: "Parents may take [weeks] weeks.",
  sources: [
    { kind: "document", id: "d1", label: "benefits.pdf" },
    { kind: "question", id: "s1", label: "parental leave duration" },
  ],
  unverified: 2,
  drafted_at: "2026-10-12T10:00:00Z",
  run_id: "r9",
};

describe("KnowledgeGapDraftCard", () => {
  beforeEach(() => {
    state.saved = [];
    state.perms = new Set(["agents:view"]);
    state.drafters = [];
    state.enabled = [];
  });

  it("points somebody who may edit the drafter at its instructions", () => {
    state.drafters = [
      { id: "own", system_key: null, can_edit: true },
      { id: "d1", system_key: "knowledge_gap_drafter", can_edit: true },
    ];
    render(<KnowledgeGapDraftCard draft={DRAFT} />);
    expect(screen.getByRole("link", { name: "Edit the drafter's instructions" })).toHaveAttribute(
      "href",
      "/agents/d1",
    );
  });

  it("does not offer the drafter to somebody who may not edit it", () => {
    state.drafters = [{ id: "d1", system_key: "knowledge_gap_drafter", can_edit: false }];
    const { unmount } = render(<KnowledgeGapDraftCard draft={DRAFT} />);
    expect(screen.queryByRole("link", { name: "Edit the drafter's instructions" })).toBeNull();
    unmount();

    state.perms = new Set();
    state.drafters = [{ id: "d1", system_key: "knowledge_gap_drafter", can_edit: true }];
    render(<KnowledgeGapDraftCard draft={DRAFT} />);
    expect(state.enabled.at(-1)).toBe(false);
    expect(screen.queryByRole("link", { name: "Edit the drafter's instructions" })).toBeNull();
  });

  it("labels it a draft and names what it was checked against", () => {
    render(<KnowledgeGapDraftCard draft={DRAFT} />);
    expect(screen.getByText("Draft — verify before adding")).toBeInTheDocument();
    expect(screen.getByText("Parental leave")).toBeInTheDocument();
    expect(screen.getByText(/Check every fact/)).toBeInTheDocument();
    expect(screen.getByText("benefits.pdf")).toBeInTheDocument();
    expect(screen.getByText("parental leave duration")).toBeInTheDocument();
    expect(
      screen.getByText("2 sources it named could not be verified and were left out."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/runs?run=r9",
    );
  });

  it("downloads it as Markdown", async () => {
    render(<KnowledgeGapDraftCard draft={DRAFT} />);
    await userEvent.click(screen.getByRole("button", { name: "Download .md" }));
    expect(state.saved[0]?.name).toBe("knowledge-gap-draft.md");
    expect(await state.saved[0]?.blob.text()).toBe(
      "# Parental leave\n\nParents may take [weeks] weeks.\n",
    );
  });

  it("shows a draft with no sources, none left out and no run without inventing them", () => {
    render(
      <KnowledgeGapDraftCard draft={{ ...DRAFT, sources: [], unverified: 0, run_id: null }} />,
    );
    expect(screen.queryByRole("list", { name: "What it rests on" })).toBeNull();
    expect(screen.queryByText(/could not be verified/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Open the run" })).toBeNull();
  });
});
