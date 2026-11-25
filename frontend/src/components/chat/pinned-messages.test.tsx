import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMessagePins } from "@/hooks/use-message-pins";
import { PinnedMessages } from "./pinned-messages";

vi.mock("@/hooks/use-message-pins", () => ({ useMessagePins: vi.fn() }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const pinState = vi.hoisted(() => ({
  items: [] as {
    message_id: string;
    thread_root_message_id: string | null;
    preview: string;
  }[],
  total: 0,
  isSuccess: true,
  isLoading: false,
  isError: false,
  pendingMessageId: null as string | null,
  togglePin: vi.fn(),
  hasNextPage: false,
  isFetchingNextPage: false,
  fetchNextPage: vi.fn(),
  refetch: vi.fn(),
}));

beforeEach(() => {
  vi.resetAllMocks();
  pinState.items = [];
  pinState.total = 0;
  pinState.isSuccess = true;
  pinState.isLoading = false;
  pinState.isError = false;
  pinState.pendingMessageId = null;
  pinState.hasNextPage = false;
  pinState.isFetchingNextPage = false;
  vi.mocked(useMessagePins).mockReturnValue(pinState as never);
});

describe("PinnedMessages", () => {
  it("jumps to a saved message with its room thread root", async () => {
    pinState.items = [
      {
        message_id: "reply-1",
        thread_root_message_id: "root-1",
        preview: "The decision was approved.",
      },
    ];
    pinState.total = 1;
    const jump = vi.fn(() => document.getElementById("target")?.focus());
    render(
      <>
        <div id="target" tabIndex={-1} />
        <PinnedMessages conversationId="c-1" onJumpToMessage={jump} />
      </>,
    );

    const trigger = screen.getByRole("button", { name: "open (1)" });
    expect(trigger).toHaveAttribute("data-tour", "chat-message-pins");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "The decision was approved." }));

    expect(jump).toHaveBeenCalledExactlyOnceWith({
      messageId: "reply-1",
      threadRootMessageId: "root-1",
    });
    await waitFor(() => expect(document.getElementById("target")).toHaveFocus());
  });

  it("returns focus to the trigger when the list closes without a jump", async () => {
    const user = userEvent.setup();
    render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: /^open/ });

    await user.click(trigger);
    await user.keyboard("{Escape}");

    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("offers a bounded next page and no trigger for an unsaved conversation", () => {
    pinState.items = [{ message_id: "m-1", thread_root_message_id: null, preview: "A note" }];
    pinState.total = 51;
    pinState.hasNextPage = true;
    const { rerender } = render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "open (51)" }));
    fireEvent.click(screen.getByRole("button", { name: "loadMore" }));
    expect(pinState.fetchNextPage).toHaveBeenCalledOnce();

    rerender(<PinnedMessages conversationId={null} onJumpToMessage={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /open/ })).toBeNull();
  });

  it("does not announce an empty count before the list has loaded", () => {
    pinState.isSuccess = false;
    render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);

    expect(screen.getByRole("button", { name: "open" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "open (0)" })).toBeNull();
  });

  it("shows a loading state and an empty list after opening", () => {
    pinState.isLoading = true;
    pinState.isSuccess = false;
    const { rerender } = render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByText("loading")).toBeTruthy();

    pinState.isLoading = false;
    pinState.isSuccess = true;
    rerender(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
    expect(screen.getByText("empty")).toBeTruthy();
  });

  it("offers a retry after the pin list fails", () => {
    pinState.isError = true;
    pinState.isSuccess = false;
    const { rerender } = render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByRole("alert")).toHaveTextContent("listFailed");
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    expect(pinState.refetch).toHaveBeenCalledOnce();

    pinState.isError = false;
    rerender(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);
  });

  it("gives a redacted preview an accessible label and can unpin from the saved list", () => {
    pinState.items = [
      { message_id: "older-segment", thread_root_message_id: null, preview: "   " },
    ];
    pinState.total = 1;
    render(<PinnedMessages conversationId="c-1" onJumpToMessage={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "open (1)" }));
    expect(screen.getByRole("button", { name: "emptyPreview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "unpin" }));

    expect(pinState.togglePin).toHaveBeenCalledExactlyOnceWith("older-segment", false);
  });
});
