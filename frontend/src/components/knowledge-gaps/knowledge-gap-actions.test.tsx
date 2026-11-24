import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InImproveWizard } from "./wizard-mode";

import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { KnowledgeGapActions } from "./knowledge-gap-actions";

const state = vi.hoisted(() => ({ granted: [] as string[], setStatus: vi.fn() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useSetKnowledgeGapStatus: () => ({ mutate: state.setStatus, isPending: false }),
}));
vi.mock("./gap-to-dataset-dialog", () => ({
  GapToDatasetDialog: ({ topicId, onClose }: { topicId: string; onClose: () => void }) => (
    <button type="button" onClick={onClose}>
      {`choose a dataset for ${topicId}`}
    </button>
  ),
}));

const TOPIC: KnowledgeGapTopic = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "parental leave",
  question_count: 2,
  asker_count: 1,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  covered_at: null,
  covered_by: null,
  has_draft: false,
  can_edit: false,
};

async function openMenu() {
  await userEvent.click(screen.getByRole("button", { name: "More actions for this topic" }));
}

describe("KnowledgeGapActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [];
  });

  it("offers nothing to a caller who can change neither the topic nor read a dataset", () => {
    const { container } = render(<KnowledgeGapActions topic={TOPIC} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dismisses an open topic, for a caller who may change its knowledge base", async () => {
    render(<KnowledgeGapActions topic={{ ...TOPIC, can_edit: true }} />);
    await openMenu();
    expect(screen.queryByRole("menuitem", { name: "Add to dataset" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Dismiss" }));
    expect(state.setStatus).toHaveBeenCalledWith({ topicId: "t1", status: "dismissed" });
  });

  it("follows the topic rather than the role: an editor's role reaches no topic it cannot change", () => {
    state.granted = [Perm.collectionsEdit];
    const { container } = render(<KnowledgeGapActions topic={TOPIC} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["dismissed", "covered"] as const)("reopens a %s one", async (status) => {
    render(<KnowledgeGapActions topic={{ ...TOPIC, status, can_edit: true }} />);
    await openMenu();
    await userEvent.click(screen.getByRole("menuitem", { name: "Reopen" }));
    expect(state.setStatus).toHaveBeenCalledWith({ topicId: "t1", status: "open" });
  });

  it("adds to a dataset without offering Dismiss, for a caller who reads datasets", async () => {
    state.granted = [Perm.datasetsView];
    render(<KnowledgeGapActions topic={TOPIC} />);
    await openMenu();
    expect(screen.queryByRole("menuitem", { name: "Dismiss" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Add to dataset" }));
    await userEvent.click(screen.getByRole("button", { name: "choose a dataset for t1" }));
    expect(screen.queryByRole("button", { name: "choose a dataset for t1" })).toBeNull();
  });

  it("offers no way to a dataset inside the Improve wizard", async () => {
    state.granted = [Perm.datasetsView];
    const { container } = render(
      <InImproveWizard.Provider value>
        <KnowledgeGapActions topic={TOPIC} />
      </InImproveWizard.Provider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
