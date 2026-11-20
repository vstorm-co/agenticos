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
