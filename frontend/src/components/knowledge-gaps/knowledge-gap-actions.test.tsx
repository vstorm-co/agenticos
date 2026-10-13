import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  has_draft: false,
};

describe("KnowledgeGapActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [];
  });

  it("offers nothing to a caller who edits neither the collection nor a dataset", () => {
    const { container } = render(<KnowledgeGapActions topic={TOPIC} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dismisses an open topic, for a caller who edits collections", async () => {
    state.granted = [Perm.collectionsEdit];
    render(<KnowledgeGapActions topic={TOPIC} />);
    expect(screen.queryByRole("button", { name: "Add to dataset" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(state.setStatus).toHaveBeenCalledWith({ topicId: "t1", status: "dismissed" });
  });

  it("reopens a dismissed one", async () => {
    state.granted = [Perm.collectionsEdit];
    render(<KnowledgeGapActions topic={{ ...TOPIC, status: "dismissed" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
    expect(state.setStatus).toHaveBeenCalledWith({ topicId: "t1", status: "open" });
  });

  it("adds to a dataset without offering Dismiss, for a caller who edits only datasets", async () => {
    state.granted = [Perm.datasetsEdit];
    render(<KnowledgeGapActions topic={TOPIC} />);
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Add to dataset" }));
    await userEvent.click(screen.getByRole("button", { name: "choose a dataset for t1" }));
    expect(screen.queryByRole("button", { name: "choose a dataset for t1" })).toBeNull();
  });
});
