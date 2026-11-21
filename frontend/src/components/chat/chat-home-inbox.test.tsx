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
vi.mock("./suggestion-actions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./suggestion-actions")>()),
  useSuggestionSource: () => ({ sourceOf: () => ({ name: "Notion" }) }),
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

it("limits the timeline preview and keeps approval and item links without a visual header", () => {
  state.items = [
    suggestion("a"),
    suggestion("b"),
    suggestion("c"),
    { ...suggestion("urgent", true), created_at: "2026-11-20T09:00:00Z" },
  ];
  state.pending = 2;
  render(<ChatHomeInbox onDiscuss={vi.fn()} />);
  const list = screen.getByRole("list");
  expect(within(list).getAllByRole("listitem")).toHaveLength(1);
  expect(within(list).getByRole("button")).toHaveTextContent("Topic urgent");
  expect(screen.queryByText("Topic c")).toBeNull();
  const approvalLink = screen.getByRole("link", { name: "2 approvals need your attention" });
  expect(approvalLink).toHaveAttribute("href", "/runs?tab=approvals");
  expect(within(approvalLink).getByText("Approvals")).toBeVisible();
  expect(within(approvalLink).getByText("2")).toBeVisible();
  expect(screen.getByRole("region", { name: "Daily briefing" })).toContainElement(approvalLink);
  expect(screen.queryByText("Daily briefing")).toBeNull();
  expect(screen.getByRole("link", { name: "Open inbox" })).toHaveAttribute("href", "/inbox");
});

it("shows at most two entries and includes older priority items before newer regular items", () => {
  state.items = [
    ...Array.from({ length: 5 }, (_, index) => ({
      ...suggestion(String(index)),
      created_at: `2026-11-20T0${index}:00:00Z`,
    })),
    { ...suggestion("older-priority", true), created_at: "2026-11-18T09:00:00Z" },
    suggestion("newer-priority", true),
  ];
  render(<ChatHomeInbox onDiscuss={vi.fn()} />);
  const entries = within(screen.getByRole("list")).getAllByRole("button");
  expect(entries.map((entry) => entry.textContent)).toEqual([
    expect.stringContaining("Topic newer-priority"),
    expect.stringContaining("Topic older-priority"),
  ]);
  expect(screen.getAllByText("Urgent")).toHaveLength(2);
  expect(screen.getAllByText("Urgent")[0]).toHaveClass("text-warning-ink", "bg-warning/12");
});

it("makes the entire undated row compose an editable question about the picked item", async () => {
  state.items = [
    suggestion("older"),
    { ...suggestion("latest"), created_at: "2026-11-20T10:15:00Z" },
  ];
  const discuss = vi.fn();
  render(<ChatHomeInbox onDiscuss={discuss} />);
  expect(screen.getByRole("list").tagName).toBe("OL");
  const [latest, older] = screen.getAllByRole("listitem");
  if (!latest || !older) throw new Error("Expected two timeline entries");
  expect(latest.querySelector("time")).toBeNull();
  expect(older).toHaveTextContent("Topic older");
  const action = within(latest).getByRole("button", { name: /Topic latest/ });
  expect(within(latest).getAllByRole("button")).toHaveLength(1);
  await userEvent.click(action);
  expect(discuss).toHaveBeenCalledExactlyOnceWith("Does Inbox item latest need my attention?");
});

it("does not turn a failed read into an empty inbox and retries both reads", async () => {
  state.pendingError = new Error("offline");
  render(<ChatHomeInbox onDiscuss={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("Your inbox could not be loaded.");
  expect(screen.queryByText(/all caught up/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
  expect(state.refetchPending).toHaveBeenCalledOnce();
});

it("shows loading before declaring the inbox empty", () => {
  state.loading = true;
  const { rerender } = render(<ChatHomeInbox onDiscuss={vi.fn()} />);
  expect(screen.getByRole("region", { name: "Daily briefing" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  expect(screen.queryByText(/all caught up/)).toBeNull();
  state.loading = false;
  rerender(<ChatHomeInbox onDiscuss={vi.fn()} />);
  expect(screen.getByText(/all caught up/)).toBeVisible();
});

it("keeps cached topics visible when a background refresh fails", () => {
  state.items = [suggestion("cached")];
  state.error = new Error("offline");
  render(<ChatHomeInbox onDiscuss={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Could not refresh your inbox. Showing the last loaded items.",
  );
  expect(screen.getByRole("button", { name: /Topic cached/ })).toBeVisible();
  expect(screen.queryByText(/all caught up/)).not.toBeInTheDocument();
});
