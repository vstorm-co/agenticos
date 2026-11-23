import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeGapDialog } from "./knowledge-gap-dialog";

const state = vi.hoisted(() => ({ detail: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGap: () => state.detail,
}));
vi.mock("./knowledge-gap-draft", () => ({
  KnowledgeGapDraftPanel: ({
    topic,
    onDirtyChange,
  }: {
    topic: { id: string };
    onDirtyChange: (dirty: boolean) => void;
  }) => (
    <div>
      <p>{`draft for ${topic.id}`}</p>
      <button onClick={() => onDirtyChange(true)}>Edit draft</button>
    </div>
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

  it("counts test questions apart from the people who asked", () => {
    answer({ topic: { ...TOPIC, question_count: 1, asker_count: 0, test_question_count: 1 } });
    const { rerender } = render(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} />);
    expect(screen.getByText("Came up in 1 test question in Handbook")).toBeInTheDocument();
    expect(screen.queryByText(/by one person/)).toBeNull();
    answer({ topic: { ...TOPIC, question_count: 3, asker_count: 1, test_question_count: 2 } });
    rerender(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} />);
    expect(
      screen.getByText("Asked once by one person, and in 2 test questions, in Handbook"),
    ).toBeInTheDocument();
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

  it("links no run from a question inside the Improve wizard", async () => {
    answer({ topic: TOPIC });
    const view = render(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: "Why this is needed (1)" }));
    expect(screen.getAllByRole("link", { name: "Open the run" }).length).toBeGreaterThan(0);
    view.unmount();
    render(<KnowledgeGapDialog topicId="t1" onClose={vi.fn()} wizard />);
    expect(screen.queryByRole("link", { name: "Open the run" })).toBeNull();
  });
});

it("preserves an edited draft across evidence tabs and asks before discarding it", async () => {
  answer({ topic: TOPIC });
  const close = vi.fn();
  render(<KnowledgeGapDialog topicId="t1" onClose={close} />);
  await userEvent.click(screen.getByRole("button", { name: "Edit draft" }));
  await userEvent.click(screen.getByRole("tab", { name: "Why this is needed (1)" }));
  expect(screen.getByRole("tab", { name: "Why this is needed (1)" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await userEvent.click(screen.getByRole("tab", { name: "Suggested document" }));
  expect(screen.getByText("draft for t1")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Discard unsaved changes?" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(close).not.toHaveBeenCalled();
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(close).toHaveBeenCalledOnce();
});

it("does not warn about an unsaved draft after its document was added", async () => {
  answer({ topic: TOPIC });
  const close = vi.fn();
  const view = render(<KnowledgeGapDialog topicId="t1" onClose={close} />);
  await userEvent.click(screen.getByRole("button", { name: "Edit draft" }));
  answer({ topic: { ...TOPIC, status: "covered" } });
  view.rerender(<KnowledgeGapDialog topicId="t1" onClose={close} />);
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
  expect(screen.queryByRole("heading", { name: "Discard unsaved changes?" })).toBeNull();
});
