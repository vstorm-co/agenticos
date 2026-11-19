import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "@/types";
import { RoomThreadButton } from "./room-thread-button";

function saved(changes: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "root-a",
    role: "user",
    content: "The launch plan",
    timestamp: new Date("2026-11-14T00:00:00Z"),
    conversationId: "room-a",
    ...changes,
  };
}

describe("a saved message's thread action", () => {
  it.each(["user", "assistant"] as const)(
    "opens the selected %s message as a root when the reader can post",
    async (role) => {
      const open = vi.fn();
      render(<RoomThreadButton message={saved({ role })} canStart onOpen={open} />);
      await userEvent.click(screen.getByRole("button", { name: "Reply in thread" }));
      expect(open).toHaveBeenCalledExactlyOnceWith("root-a");
    },
  );

  it.each([
    ["an unsaved message", { isTemporaryId: true }],
    ["a streaming answer", { isStreaming: true }],
    ["a system event", { role: "system" }],
    ["an empty bubble", { content: "" }],
  ] satisfies [string, Partial<ChatMessage>][])(
    "does not offer a new discussion for %s",
    (_description, changes) => {
      render(<RoomThreadButton message={saved(changes)} canStart onOpen={vi.fn()} />);
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    },
  );

  it("hides creation from a reader without posting permission", () => {
    render(
      <RoomThreadButton
        message={saved({ threadReplyCount: 0 })}
        canStart={false}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps an unread thread openable for a read-only reader and announces the unread count", async () => {
    const open = vi.fn();
    render(
      <RoomThreadButton
        message={saved({
          threadSummary: {
            state: "open",
            following: false,
            unread: 4,
            can_manage: false,
          },
        })}
        canStart={false}
        onOpen={open}
      />,
    );
    const button = screen.getByRole("button", { name: "Reply in thread" });
    expect(button).toHaveAttribute("aria-describedby", "room-thread-unread-root-a");
    expect(screen.getByText("4 unread replies")).toBeInTheDocument();
    await userEvent.click(button);
    expect(open).toHaveBeenCalledExactlyOnceWith("root-a");
  });

  it.each([
    [1, "1 reply"],
    [4, "4 replies"],
  ] as const)("lets a reader open an existing discussion with %i replies", async (count, label) => {
    const open = vi.fn();
    render(
      <RoomThreadButton
        message={saved({ threadReplyCount: count })}
        canStart={false}
        onOpen={open}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: label }));
    expect(open).toHaveBeenCalledExactlyOnceWith("root-a");
  });

  it("replaces creation with the refreshed reply count without changing its root", async () => {
    const open = vi.fn();
    const { rerender } = render(<RoomThreadButton message={saved()} canStart onOpen={open} />);
    expect(screen.getByRole("button", { name: "Reply in thread" })).toBeInTheDocument();
    rerender(<RoomThreadButton message={saved({ threadReplyCount: 2 })} canStart onOpen={open} />);
    expect(screen.queryByRole("button", { name: "Reply in thread" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "2 replies" }));
    expect(open).toHaveBeenCalledExactlyOnceWith("root-a");
  });
});
