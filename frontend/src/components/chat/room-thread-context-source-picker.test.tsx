import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RoomThreadContextSourcePicker } from "./room-thread-context-source-picker";

const { search, fetchNextPage } = vi.hoisted(() => ({
  search: vi.fn(),
  fetchNextPage: vi.fn(),
}));

vi.mock("@/hooks/use-room-thread-context", () => ({
  useRoomThreadContextConversationSearch: (term: string) => search(term),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  search.mockImplementation((term: string) => ({
    items:
      term === "needle"
        ? [
            {
              id: "shared-51",
              title: "Needle after page one",
              created_at: "2026-11-01T00:00:00Z",
              updated_at: null,
              is_archived: false,
              share_permission: "view",
            },
          ]
        : [],
    isError: false,
    isFetching: false,
    isFetchingNextPage: false,
    hasNextPage: term === "needle",
    fetchNextPage,
    refetch: vi.fn(),
  }));
});

afterEach(() => vi.useRealTimers());

describe("RoomThreadContextSourcePicker", () => {
  it("debounces search, pages to later matches, and only selects the source", () => {
    const onChange = vi.fn();
    render(
      <RoomThreadContextSourcePicker
        destinationConversationId="room-a"
        destinationTitle="Room A"
        sourceConversationId="room-a"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose source conversation" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "needle " },
    });

    act(() => vi.advanceTimersByTime(249));
    expect(search).not.toHaveBeenCalledWith("needle");
    act(() => vi.advanceTimersByTime(1));
    expect(search).toHaveBeenCalledWith("needle");
    expect(screen.getByRole("option", { name: /Needle after page one/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more conversations" }));
    expect(fetchNextPage).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("option", { name: /Needle after page one/ }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("shared-51", "Needle after page one");
  });
});

describe("RoomThreadContextSourcePicker states", () => {
  const state = (overrides: Record<string, unknown> = {}) => ({
    items: [],
    error: null,
    isError: false,
    isFetching: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    fetchNextPage,
    refetch: vi.fn(),
    ...overrides,
  });
  const picker = (props: Record<string, unknown> = {}) => (
    <RoomThreadContextSourcePicker
      destinationConversationId="room-a"
      destinationTitle=""
      sourceConversationId="room-a"
      onChange={vi.fn()}
      {...props}
    />
  );
  const open = () =>
    fireEvent.click(screen.getByRole("button", { name: "Choose source conversation" }));
  const type = (value: string) => {
    fireEvent.change(screen.getByRole("searchbox"), { target: { value } });
    act(() => vi.advanceTimersByTime(250));
  };

  it("names an untitled destination and closes again", () => {
    search.mockReturnValue(state());
    const onChange = vi.fn();
    render(picker({ onChange }));
    expect(screen.getByText("Untitled conversation")).toBeInTheDocument();

    open();
    expect(screen.getByText(/Access is checked when the context is saved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close conversation picker" }));
    expect(screen.queryByRole("listbox")).toBeNull();

    open();
    fireEvent.click(screen.getByRole("option", { name: /Untitled conversation/ }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("room-a", "");
  });

  it("names a source it has not searched for by its known title, else generically", () => {
    search.mockReturnValue(state());
    const view = render(picker({ sourceConversationId: "room-b", sourceTitle: "Known" }));
    expect(screen.getByText("Known")).toBeInTheDocument();
    view.rerender(picker({ sourceConversationId: "room-b" }));
    expect(screen.getByText("Selected conversation")).toBeInTheDocument();
  });

  it("offers a retry when the search fails", () => {
    const refetch = vi.fn();
    search.mockReturnValue(state({ isError: true, hasNextPage: true, refetch }));
    render(picker());
    open();
    fireEvent.click(screen.getByRole("button", { name: "Retry search" }));
    expect(refetch).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Load more conversations" })).toBeNull();
  });

  it.each([
    ["is still running", { isFetching: true }, "Searching conversations…"],
    ["found nothing", {}, "No readable conversations match that search."],
    ["has more to read", { hasNextPage: true }, "No matches in the conversations loaded so far."],
  ])("says so when the search %s", (_case, overrides, text) => {
    search.mockReturnValue(state(overrides));
    render(picker());
    open();
    type("x");
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("describes each kind of conversation and holds paging while it loads", () => {
    const found = (id: string, extra: Record<string, unknown>) => ({ id, title: id, ...extra });
    search.mockReturnValue(
      state({
        items: [
          found("open", { room_visibility: "public" }),
          found("closed", { room_visibility: "private" }),
          found("project", { project_id: "p" }),
          found("shared", { share_permission: "view" }),
          found("plain", {}),
          { id: "nameless", title: null },
        ],
        hasNextPage: true,
        isFetching: true,
        isFetchingNextPage: true,
      }),
    );
    const onChange = vi.fn();
    render(picker({ onChange, sourceConversationId: "plain" }));
    open();
    type("x");

    for (const [name, description] of [
      ["open", "Public room"],
      ["closed", "Project or private room"],
      ["project", "Project or private room"],
      ["shared", "Shared conversation"],
      ["plain", "Conversation"],
    ]) {
      expect(
        screen.getByRole("option", { name: new RegExp(`^${name}\s*${description}$`) }),
      ).toBeInTheDocument();
    }
    expect(screen.getByRole("option", { name: /^plain\s*Conversation$/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "Loading more conversations…" })).toBeDisabled();

    fireEvent.click(screen.getByRole("option", { name: /^Untitled conversation\s*Conversation$/ }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("nameless", "Untitled conversation");
  });
});
