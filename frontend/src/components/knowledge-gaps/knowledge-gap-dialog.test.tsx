import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeGapDialog } from "./knowledge-gap-dialog";

const state = vi.hoisted(() => ({ detail: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGap: () => state.detail,
}));
vi.mock("./knowledge-gap-draft", () => ({
  KnowledgeGapDraftPanel: ({ topic }: { topic: { id: string } }) => (
    <p>{`draft for ${topic.id}`}</p>
  ),
}));
vi.mock("./knowledge-gap-actions", () => ({
  KnowledgeGapActions: ({ topic }: { topic: { id: string } }) => <p>{`actions for ${topic.id}`}</p>,
}));

const TOPIC = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "How long is parental leave?",
  question_count: 2,
  asker_count: 1,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  covered_at: null,
  covered_by: null,
  has_draft: false,
  questions: [
    {
      search_id: "s1",
      query: "parental leave duration",
      question: "How long can I take parental leave?",
      top_similarity: null,
      result_count: 0,
      agent: null,
      run_id: "r1",
      conversation_id: null,
      answer_message_id: null,
      down_rating_comment: null,
      asked_at: "2026-10-12T09:00:00Z",
    },
  ],
};

function answer(overrides: Record<string, unknown>) {
  state.detail = {
    topic: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("KnowledgeGapDialog", () => {
  beforeEach(() => answer({}));

  it("shows the topic's questions and what can be done with it", () => {
    answer({ topic: TOPIC });
    render(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} />);
    expect(
      screen.getByRole("heading", { name: "How long is parental leave?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Asked 2 times by one person in Handbook")).toBeInTheDocument();
    expect(screen.getByText("actions for t1")).toBeInTheDocument();
    expect(screen.getByText("draft for t1")).toBeInTheDocument();
    expect(screen.getByText("How long can I take parental leave?")).toBeInTheDocument();
  });

  it("says the topic failed to load, and retries", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    render(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} />);
    expect(screen.getByText("This topic could not be loaded")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("waits with a skeleton, then closes on Escape", async () => {
    const onClose = vi.fn();
    answer({ isLoading: true });
    render(<KnowledgeGapDialog topicId="t1" onClose={onClose} />);
    expect(screen.getByRole("heading", { name: "Topic" })).toBeInTheDocument();
    expect(screen.queryByText("This topic could not be loaded")).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
