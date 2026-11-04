import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspacePulse } from "./workspace-pulse";
import type { Suggestion } from "@/lib/suggestions-api";
import type { ConversationTask } from "@/hooks/use-conversation-tasks";

const state = vi.hoisted(() => ({
  suggestions: [] as Suggestion[],
  tasks: [] as ConversationTask[],
  inboxError: null as Error | null,
  workError: null as Error | null,
  loading: false,
  retryInbox: vi.fn(),
  retryWork: vi.fn(),
}));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({
    suggestions: state.suggestions,
    error: state.inboxError,
    isLoading: state.loading,
    refetch: state.retryInbox,
  }),
}));
vi.mock("@/hooks/use-conversation-tasks", async (original) => ({
  ...(await original<typeof import("@/hooks/use-conversation-tasks")>()),
  useConversationTasks: () => ({
    data: state.tasks,
    error: state.workError,
    isPending: state.loading,
    refetch: state.retryWork,
  }),
}));
const suggestion = (id: string): Suggestion => ({
  id,
  title: `Decision ${id}`,
  kind: "profile",
  status: "open",
  detail: null,
  payload: {},
  created_at: "2026-11-04T12:00:00Z",
});
const task = (id: string, status: ConversationTask["status"]): ConversationTask => ({
  id,
  title: `Task ${id}`,
  status,
  conversation_id: `chat/${id}`,
  source_conversation_id: "source",
  agent_id: "agent",
  delivery: "pending",
  run_id: null,
  return_run_id: null,
  outcome: null,
  created_at: "2026-11-04T12:00:00Z",
});

beforeEach(() => {
  state.suggestions = [];
  state.tasks = [];
  state.inboxError = null;
  state.workError = null;
  state.loading = false;
});
describe("WorkspacePulse", () => {
  it("bounds the preview and links directly to the selected decision and active conversation", () => {
    state.suggestions = [suggestion("one"), suggestion("two"), suggestion("three")];
    state.tasks = [
      task("done", "completed"),
      task("one", "running"),
      task("two", "queued"),
      task("three", "running"),
    ];
    render(<WorkspacePulse />);
    expect(screen.getByRole("link", { name: "Decision one" })).toHaveAttribute(
      "href",
      "/inbox#suggestion-one",
    );
    expect(screen.getByRole("link", { name: "Task one" })).toHaveAttribute(
      "href",
      "/chat?id=chat%2Fone",
    );
    expect(screen.queryByText("Decision three")).toBeNull();
    expect(screen.queryByText("Task three")).toBeNull();
    expect(screen.queryByText("Task done")).toBeNull();
  });
  it("offers independent retries instead of claiming failed queries are empty", async () => {
    state.inboxError = new Error("offline");
    state.workError = new Error("offline");
    render(<WorkspacePulse />);
    const retries = screen.getAllByRole("button", { name: "Try again" });
    for (const retry of retries) await userEvent.click(retry);
    expect(state.retryInbox).toHaveBeenCalled();
    expect(state.retryWork).toHaveBeenCalled();
    expect(screen.queryByText("Nothing running right now")).toBeNull();
  });
});
