import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RoomThreadMovedStub } from "@/types/room-thread-context";
import { RoomThreadContextStub } from "./room-thread-context-stub";

describe("RoomThreadContextStub", () => {
  it("describes the moved message count and thread title without exposing ordinals", () => {
    const stub: RoomThreadMovedStub = {
      root_message_id: "thread-root",
      source_conversation_id: "room-a",
      first_ordinal: 22,
      last_ordinal: 24,
      message_count: 3,
      title: "Project question",
    };
    render(<RoomThreadContextStub stub={stub} onOpen={vi.fn()} />);

    const button = screen.getByRole("button", {
      name: "Open thread context for Project question",
    });
    expect(button).toHaveTextContent("3 messages moved to this thread");
    expect(button).not.toHaveTextContent("22");
    expect(button).not.toHaveTextContent("24");
  });
});

describe("RoomThreadContextStub without a thread title", () => {
  it("falls back to a generic name and opens the thread it stands for", async () => {
    const onOpen = vi.fn();
    render(
      <RoomThreadContextStub
        stub={{
          root_message_id: "thread-root",
          source_conversation_id: "room-a",
          first_ordinal: 1,
          last_ordinal: 1,
          message_count: 1,
          title: "   ",
        }}
        onOpen={onOpen}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Open thread context for Thread context" }),
    );

    expect(onOpen).toHaveBeenCalledExactlyOnceWith("thread-root");
  });
});
