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
  org: null as { id: string; ai_assistance_enabled: boolean } | null,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: state.org }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useDraftKnowledgeGap: () => ({ mutate: state.mutate, isPending: state.isPending }),
}));
vi.mock("./knowledge-gap-draft-card", () => ({
  KnowledgeGapDraftCard: ({ draft }: { draft: { title: string } }) => (
    <p>{`card ${draft.title}`}</p>
  ),
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
  can_edit: true,
  questions: [],
  draft: null,
};

const DRAFTED: KnowledgeGapTopicDetail = {
  ...TOPIC,
  has_draft: true,
  draft: {
    title: "Parental leave",
    content: "Parents may take [weeks] weeks.",
    sources: [],
    unverified: 0,
    drafted_at: "2026-10-12T10:00:00Z",
    run_id: null,
  },
};

describe("KnowledgeGapDraftPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [];
    state.isPending = false;
    state.org = { id: "o1", ai_assistance_enabled: true };
  });

  it("offers no drafting to a caller who may not run agents", () => {
    render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    expect(screen.queryByRole("button", { name: "Draft the missing content" })).toBeNull();
  });

  it("offers no drafting on a topic whose knowledge base the caller may not change", () => {
    state.granted = [Perm.agentsRun];
    render(<KnowledgeGapDraftPanel topic={{ ...DRAFTED, can_edit: false }} />);
    expect(screen.queryByRole("button", { name: "Draft again" })).toBeNull();
    expect(screen.getByText("card Parental leave")).toBeInTheDocument();
  });

  it("asks for a draft of a topic that has none", async () => {
    state.granted = [Perm.agentsRun];
    render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    await userEvent.click(screen.getByRole("button", { name: "Draft the missing content" }));
    expect(state.mutate).toHaveBeenCalledWith("t1");
  });

  it("says it is drafting while the run is in flight, beside the draft it will replace", () => {
    state.granted = [Perm.agentsRun];
    state.isPending = true;
    render(<KnowledgeGapDraftPanel topic={DRAFTED} />);
    expect(screen.getByRole("button", { name: "Drafting…" })).toBeDisabled();
    expect(screen.getByText("card Parental leave")).toBeInTheDocument();
  });

  it("offers to draft again once a draft exists", () => {
    state.granted = [Perm.agentsRun];
    render(<KnowledgeGapDraftPanel topic={DRAFTED} />);
    expect(screen.getByRole("button", { name: "Draft again" })).toBeInTheDocument();
  });

  it("with AI assistance off, sends somebody who may turn it on to the switch", () => {
    state.granted = [Perm.agentsRun, Perm.orgSettings];
    state.org = { id: "o1", ai_assistance_enabled: false };
    render(<KnowledgeGapDraftPanel topic={DRAFTED} />);
    expect(screen.queryByRole("button", { name: "Draft again" })).toBeNull();
    expect(screen.getByText(/AI assistance is off/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enable AI assistance" })).toHaveAttribute(
      "href",
      "/orgs/o1/members",
    );
    expect(screen.getByText("card Parental leave")).toBeInTheDocument();
  });

  it("with AI assistance off, tells anybody else who can turn it on", () => {
    state.granted = [Perm.agentsRun];
    state.org = { id: "o1", ai_assistance_enabled: false };
    render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    expect(screen.queryByRole("link", { name: "Enable AI assistance" })).toBeNull();
    expect(screen.getByText(/Ask an admin to turn it on/)).toBeInTheDocument();
  });

  it("says nothing about the switch before the organization is known", () => {
    state.granted = [Perm.agentsRun];
    state.org = null;
    const { container } = render(<KnowledgeGapDraftPanel topic={TOPIC} />);
    expect(container.querySelector("section")).toBeEmptyDOMElement();
  });
});
