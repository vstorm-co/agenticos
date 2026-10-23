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
  history: [] as Suggestion[],
  restore: vi.fn(),
  shown: [] as Suggestion[],
  filter: null as string | null,
  push: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({ suggestions: state.open }),
  useSuggestionHistory: () => ({ history: state.history, restore: state.restore }),
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
  });

  it("says nothing waits, and sends the person to set up a watch", async () => {
    render(<InboxPage />);
    expect(screen.getByText("Nothing waits here")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set up a watch" }));
    expect(state.push).toHaveBeenCalledWith("/routines");

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
