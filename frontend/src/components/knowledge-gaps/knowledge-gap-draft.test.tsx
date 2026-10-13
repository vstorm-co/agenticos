import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopicDetail } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftPanel } from "./knowledge-gap-draft";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  mutate: vi.fn(),
  isPending: false,
  saved: [] as { blob: Blob; name: string }[],
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useDraftKnowledgeGap: () => ({ mutate: state.mutate, isPending: state.isPending }),
}));
vi.mock("@/lib/file-access", () => ({
  saveBlob: (blob: Blob, name: string) => state.saved.push({ blob, name }),
}));

const TOPIC: KnowledgeGapTopicDetail = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "parental leave",
  question_count: 2,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  has_draft: false,
  questions: [],
  draft: null,
};

const DRAFTED: KnowledgeGapTopicDetail = {
  ...TOPIC,
  has_draft: true,
  draft: {
    title: "Parental leave",
    content: "Parents may take [weeks] weeks.",
    answers: [],
    sources: ["benefits.pdf"],
    drafted_at: "2026-10-12T10:00:00Z",
    run_id: "r9",
  },
};

describe("KnowledgeGapDraftPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [];
    state.isPending = false;
    state.saved = [];
  });

  it("offers no drafting to a caller who may not run agents", () => {
    render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    expect(screen.queryByRole("button", { name: "Draft the missing content" })).toBeNull();
  });

  it("asks for a draft of a topic that has none", async () => {
    state.granted = [Perm.agentsRun];
    render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    await userEvent.click(screen.getByRole("button", { name: "Draft the missing content" }));
    expect(state.mutate).toHaveBeenCalledWith("t1");
  });

  it("says it is drafting while the run is in flight", () => {
    state.granted = [Perm.agentsRun];
    state.isPending = true;
    render(<KnowledgeGapDraftPanel topic={DRAFTED} />);
    expect(screen.getByRole("button", { name: "Drafting…" })).toBeDisabled();
  });

  it("shows a draft as a draft, with its sources and run, and downloads it as Markdown", async () => {
    state.granted = [Perm.agentsRun];
    render(<KnowledgeGapDraftPanel topic={DRAFTED} />);
    expect(screen.getByRole("button", { name: "Draft again" })).toBeInTheDocument();
    expect(screen.getByText("Draft: Parental leave")).toBeInTheDocument();
    expect(screen.getByText(/Check every fact/)).toBeInTheDocument();
    expect(screen.getByText("Uses: benefits.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/runs?run=r9",
    );
    await userEvent.click(screen.getByRole("button", { name: "Download .md" }));
    expect(state.saved[0]?.name).toBe("knowledge-gap-draft.md");
    expect(await state.saved[0]?.blob.text()).toBe(
      "# Parental leave\n\nParents may take [weeks] weeks.\n",
    );
  });

  it("shows a draft with no sources or run without inventing them", () => {
    const bare = { ...DRAFTED, draft: { ...DRAFTED.draft!, sources: [], run_id: null } };
    render(<KnowledgeGapDraftPanel topic={bare} />);
    expect(screen.queryByText(/Uses:/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Open the run" })).toBeNull();
  });
});
