import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InboxPage } from "./inbox-page";
import type { Suggestion } from "@/lib/suggestions-api";

/**
 * The inbox (#2301): what waits, narrowed by where it came from, and what was
 * already answered - with a declined one brought back.
 */

const state = vi.hoisted(() => ({
  open: [] as Suggestion[],
  loading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  history: [] as Suggestion[],
  restore: vi.fn(),
  shown: [] as Suggestion[],
  filter: null as string | null,
  push: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({
    suggestions: state.open,
    isLoading: state.loading,
    error: state.error,
    refetch: state.refetch,
  }),
  useSuggestionHistory: () => ({
    history: state.history,
    restore: state.restore,
    isLoading: state.loading,
    error: state.error,
    refetch: state.refetch,
  }),
}));
vi.mock("./suggestion-rows", () => ({
  SuggestionRows: ({ items }: { items: Suggestion[] }) => {
    state.shown = items;
    return <div data-testid="rows" />;
  },
}));
vi.mock("@/hooks", () => ({ useMcpCatalog: () => ({ servers: [] }) }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(state.filter ? { filter: state.filter } : {}),
  useRouter: () => ({ push: state.push }),
  usePathname: () => "/inbox",
}));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

function item(id: string, overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id,
    kind: "routine",
    status: "open",
    title: `Title ${id}`,
    detail: null,
    payload: {},
    created_at: "2026-10-23T06:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  state.open = [];
  state.loading = false;
  state.error = null;
  state.refetch.mockReset();
  state.history = [];
  state.shown = [];
  state.filter = null;
  state.push.mockReset();
  state.restore.mockReset().mockResolvedValue(undefined);
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("InboxPage", () => {
  it("narrows what waits to the urgent, the watches' or the suggestions", async () => {
    const finding = item("f", { kind: "finding" });
    const urgent = item("u", { kind: "finding", urgent: true });
    const routine = item("r");
    state.open = [finding, urgent, routine];
    render(<InboxPage />);

    expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(screen.getByText("3 waiting")).toBeInTheDocument();
    expect(state.shown).toEqual([finding, urgent, routine]);
    await userEvent.click(screen.getByRole("radio", { name: "Urgent" }));
    expect(state.shown).toEqual([urgent]);
    await userEvent.click(screen.getByRole("radio", { name: "From watches" }));
    expect(state.shown).toEqual([finding, urgent]);
    await userEvent.click(screen.getByRole("radio", { name: "Suggestions" }));
    expect(state.shown).toEqual([routine]);
    await userEvent.click(screen.getByRole("radio", { name: "All" }));
    expect(state.shown).toEqual([finding, urgent, routine]);
  });

  it("says nothing waits, and sends the person to set up a watch", async () => {
    render(<InboxPage />);
    expect(screen.getByText("Nothing waits here")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set up a watch" }));
    expect(state.push).toHaveBeenCalledWith("/routines?tab=watches");

    // Nothing urgent is not a reason to set up a watch.
    await userEvent.click(screen.getByRole("radio", { name: "Urgent" }));
    expect(screen.queryByRole("button", { name: "Set up a watch" })).toBeNull();
  });

  it("opens already narrowed to what a link asked for, and ignores what it does not know", () => {
    state.open = [item("f", { kind: "finding" }), item("r")];
    state.filter = "watches";
    const { unmount } = render(<InboxPage />);
    expect(screen.getByRole("radio", { name: "From watches" })).toBeChecked();
    expect(state.shown.map((each) => each.id)).toEqual(["f"]);
    unmount();

    state.filter = "spam";
    render(<InboxPage />);
    expect(screen.getByRole("radio", { name: "All" })).toBeChecked();
  });

  it("lists what was answered and brings a declined one back", async () => {
    state.history = [
      item("open"),
      item("took", { status: "accepted", detail: "Saved" }),
      item("no", { status: "dismissed" }),
    ];
    render(<InboxPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Done" }));

    expect(screen.queryByText("Title open")).toBeNull();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Bring back" }));
    expect(state.restore).toHaveBeenCalledWith("no");
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("toasts a restore the server refused, and says when nothing was answered", async () => {
    state.history = [item("no", { status: "dismissed" })];
    state.restore.mockRejectedValue(new Error("Server down"));
    const { unmount } = render(<InboxPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Done" }));
    await userEvent.click(screen.getByRole("button", { name: "Bring back" }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    unmount();

    state.history = [];
    render(<InboxPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Done" }));
    expect(screen.getByText("Nothing answered yet")).toBeInTheDocument();
  });
});

it("does not announce an empty inbox while its data is still loading", () => {
  state.loading = true;
  render(<InboxPage />);
  expect(screen.queryByText("Nothing waits here")).not.toBeInTheDocument();
  expect(screen.queryByText("Nothing waiting")).not.toBeInTheDocument();
});

it("shows a retry for a failed read instead of claiming nothing waits", async () => {
  state.error = new Error("offline");
  render(<InboxPage />);
  expect(screen.queryByText("Nothing waits here")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});

it("applies a watch-filter link while the inbox is already open", () => {
  const finding = item("finding", { kind: "finding" });
  state.open = [finding, item("routine")];
  const { rerender } = render(<InboxPage />);
  state.filter = "watches";
  rerender(<InboxPage />);
  expect(state.shown).toEqual([finding]);
});

it("lets the person retry a failed Done history read", async () => {
  state.error = new Error("offline");
  render(<InboxPage />);
  await userEvent.click(screen.getByRole("radio", { name: "Done" }));
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});

it("keeps Done history in a loading state until its read finishes", () => {
  state.filter = "done";
  state.loading = true;
  const { rerender } = render(<InboxPage />);
  expect(screen.queryByText("Nothing answered yet")).not.toBeInTheDocument();
  state.loading = false;
  state.history = [item("done", { status: "accepted" })];
  rerender(<InboxPage />);
  expect(screen.getByText("Title done")).toBeInTheDocument();
});
