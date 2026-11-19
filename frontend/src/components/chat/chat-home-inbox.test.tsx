import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Suggestion } from "@/lib/suggestions-api";
import { ChatHomeInbox } from "./chat-home-inbox";

const state = vi.hoisted(() => ({
  items: [] as Suggestion[],
  loading: false,
  error: null as Error | null,
  pending: 0,
  pendingError: null as Error | null,
  refetch: vi.fn(),
  refetchPending: vi.fn(),
}));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({
    suggestions: state.items,
    isLoading: state.loading,
    error: state.error,
    refetch: state.refetch,
  }),
}));
vi.mock("@/hooks/use-pending-approvals", () => ({
  usePendingApprovals: () => ({
    count: state.pending,
    isLoading: false,
    error: state.pendingError,
    refetch: state.refetchPending,
  }),
}));
vi.mock("./suggestion-actions", () => ({
  useSuggestionSource: () => ({ sourceOf: () => ({ name: "Notion" }) }),
  urgentFirst: (items: Suggestion[]) =>
    [...items].sort((a, b) => Number(!!b.urgent) - Number(!!a.urgent)),
  SuggestionMark: ({ suggestion }: { suggestion: Suggestion }) => (
    <span>{String(suggestion.payload.server)}</span>
  ),
}));
beforeEach(() => {
  state.items = [];
  state.loading = false;
  state.error = null;
  state.pending = 0;
  state.pendingError = null;
  vi.clearAllMocks();
});
const suggestion = (id: string, urgent = false): Suggestion => ({
  id,
  title: `Topic ${id}`,
  detail: "A summary",
  kind: "finding",
  status: "open",
  urgent,
  payload: { server: "notion" },
  created_at: "2026-11-19T09:00:00Z",
});

it("prioritizes urgent topics, limits the preview and links to actual inbox rows", () => {
  state.items = [suggestion("a"), suggestion("b"), suggestion("c"), suggestion("urgent", true)];
  state.pending = 2;
  render(<ChatHomeInbox />);
  const list = screen.getByRole("list");
  expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  expect(within(list).getAllByRole("link")[0]).toHaveAttribute("href", "/inbox#suggestion-urgent");
  expect(screen.queryByText("Topic c")).toBeNull();
  const approvalLink = screen.getByRole("link", { name: "2 approvals need your attention" });
  expect(approvalLink).toHaveAttribute("href", "/runs?tab=approvals");
  expect(within(approvalLink).getByText("Approvals")).toBeVisible();
  expect(within(approvalLink).getByText("2")).toBeVisible();
  expect(approvalLink.closest("header")).toContainElement(
    screen.getByRole("heading", { name: "Daily briefing" }),
  );
  expect(screen.getByRole("heading", { name: "Daily briefing" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Open inbox" })).toHaveAttribute("href", "/inbox");
});

it("shows up to eight entries in the expanded Inbox", () => {
  state.items = Array.from({ length: 10 }, (_, index) => suggestion(String(index)));
  render(<ChatHomeInbox expanded />);
  expect(within(screen.getByRole("list")).getAllByRole("listitem")).toHaveLength(8);
  expect(screen.getByRole("link", { name: /Topic 7/ })).toBeVisible();
});

it("does not turn a failed read into an empty inbox and retries both reads", async () => {
  state.pendingError = new Error("offline");
  render(<ChatHomeInbox />);
  expect(screen.getByRole("status")).toHaveTextContent("Your inbox could not be loaded.");
  expect(screen.queryByText(/all caught up/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
  expect(state.refetchPending).toHaveBeenCalledOnce();
});

it("shows loading before declaring the inbox empty", () => {
  state.loading = true;
  const { rerender } = render(<ChatHomeInbox />);
  expect(screen.getByRole("region", { name: "Daily briefing" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  expect(screen.queryByText(/all caught up/)).toBeNull();
  state.loading = false;
  rerender(<ChatHomeInbox />);
  expect(screen.getByText(/all caught up/)).toBeVisible();
});

it("keeps cached topics visible when a background refresh fails", () => {
  state.items = [suggestion("cached")];
  state.error = new Error("offline");
  render(<ChatHomeInbox />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Could not refresh your inbox. Showing the last loaded items.",
  );
  expect(screen.getByRole("link", { name: /Topic cached/ })).toBeVisible();
  expect(screen.queryByText(/all caught up/)).not.toBeInTheDocument();
});
