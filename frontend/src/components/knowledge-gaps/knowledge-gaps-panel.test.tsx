import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeGapsPanel } from "./knowledge-gaps-panel";

const state = vi.hoisted(() => ({
  list: {} as Record<string, unknown>,
  calls: [] as unknown[][],
  granted: [] as string[],
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: (...args: unknown[]) => {
    state.calls.push(args);
    return state.list;
  },
  useRegroupKnowledgeGaps: () => ({ mutate: vi.fn(), isPending: false }),
  useSetKnowledgeGapStatus: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("./knowledge-gap-dialog", () => ({
  KnowledgeGapDialog: ({ topicId, onClose }: { topicId: string; onClose: () => void }) => (
    <button type="button" onClick={onClose}>
      {`dialog ${topicId}`}
    </button>
  ),
}));

const TOPIC = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "How long is parental leave?",
  question_count: 4,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [
    { id: "a1", name: "HR helper", slug: "hr-helper", has_avatar: false, avatar_color: null },
  ],
  dismissed_at: null,
  has_draft: false,
  can_edit: false,
};

function answer(overrides: Record<string, unknown> = {}) {
  state.list = {
    topics: [],
    total: 0,
    ungrouped: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("KnowledgeGapsPanel", () => {
  beforeEach(() => {
    state.calls = [];
    state.granted = [];
    answer();
  });

  it("lists a collection's open topics, with how often and by which agents", () => {
    answer({ topics: [TOPIC], total: 1 });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(state.calls[0]).toEqual([
      { kind: "collection", id: "kb1" },
      { status: "open", skip: 0, limit: 50 },
    ]);
    expect(screen.getByText("How long is parental leave?")).toBeInTheDocument();
    expect(screen.getByText("Asked 4 times")).toBeInTheDocument();
    expect(screen.getByText("HR helper")).toBeInTheDocument();
    // On a collection's own tab, which knowledge base it is goes without saying.
    expect(screen.queryByText("Handbook")).toBeNull();
    expect(
      screen.getByText(/Nothing is added to a knowledge base automatically/),
    ).toBeInTheDocument();
  });

  it("names the knowledge base on an agent's list, where topics come from several", () => {
    answer({ topics: [TOPIC], total: 1 });
    render(<KnowledgeGapsPanel scope={{ kind: "agent", id: "a1" }} />);
    expect(screen.getByText("Handbook")).toBeInTheDocument();
  });

  it("marks a topic that already has a draft", () => {
    answer({ topics: [{ ...TOPIC, has_draft: true }], total: 1 });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("says how many questions wait for the next grouping pass", () => {
    answer({ ungrouped: 2 });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.getByText(/2 questions are waiting to be grouped/)).toBeInTheDocument();
  });

  it("offers grouping now only when the list says the caller may change the base", () => {
    answer({ canRegroup: true });
    const { unmount } = render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.getByRole("button", { name: "Group now" })).toBeInTheDocument();
    unmount();
    answer({ canRegroup: false });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.queryByRole("button", { name: "Group now" })).toBeNull();
  });

  it("renders a failed request as an error with a retry, never as an empty list", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.queryByText("No open knowledge gaps")).toBeNull();
    expect(screen.getByText("Knowledge gaps could not be loaded")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading, and neither empty nor error", () => {
    answer({ isLoading: true });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.queryByText("No open knowledge gaps")).toBeNull();
    expect(screen.queryByText("Knowledge gaps could not be loaded")).toBeNull();
  });

  it("switches to the dismissed topics from the first page, with their own empty state", async () => {
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    expect(screen.getByText("No open knowledge gaps")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Show topics" }));
    await userEvent.click(screen.getByRole("option", { name: "Dismissed" }));
    expect(state.calls.at(-1)).toEqual([
      { kind: "collection", id: "kb1" },
      { status: "dismissed", skip: 0, limit: 50 },
    ]);
    expect(screen.getByText("No dismissed topics")).toBeInTheDocument();
  });

  it("pages through a long list", async () => {
    answer({ topics: [TOPIC], total: 120 });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    await userEvent.click(screen.getByRole("button", { name: /next page/i }));
    expect(state.calls.at(-1)?.[1]).toEqual({ status: "open", skip: 50, limit: 50 });
  });

  it("opens a topic and closes it again", async () => {
    answer({ topics: [TOPIC], total: 1 });
    render(<KnowledgeGapsPanel scope={{ kind: "collection", id: "kb1" }} />);
    await userEvent.click(screen.getByRole("button", { name: /parental leave/ }));
    await userEvent.click(screen.getByRole("button", { name: "dialog t1" }));
    expect(screen.queryByRole("button", { name: "dialog t1" })).toBeNull();
  });
});
