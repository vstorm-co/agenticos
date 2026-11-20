import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConversationMessage } from "@/types/conversation";
import type { RoomThreadContextRead } from "@/types/room-thread-context";
import { RoomThreadContextRangeSelector } from "./room-thread-context-range-selector";

function message(id: string, overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id,
    conversation_id: "source-room",
    role: "user",
    content: id,
    created_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

describe("RoomThreadContextRangeSelector", () => {
  it("keeps top-level messages with replies selectable and omits title from context updates", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const initial: RoomThreadContextRead = {
      source_conversation_id: "source-room",
      start_message_id: "deleted-start",
      end_message_id: "deleted-end",
      first_ordinal: 1,
      last_ordinal: 3,
      excluded_message_ids: [],
      message_ids: [],
      message_count: 0,
      moved: false,
      revision: 7,
      stale: true,
    };
    render(
      <RoomThreadContextRangeSelector
        mode="edit"
        sourceConversationId="source-room"
        messages={[
          message("root with replies", { ordinal: 4, thread_reply_count: 3 }),
          message("nested reply", { ordinal: 5, thread_root_message_id: "another-root" }),
        ]}
        rootMessageId="this-root"
        initial={initial}
        title="Existing thread title"
        onSubmit={onSubmit}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Set range start at: root with replies" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("nested reply")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Set range start at: root with replies" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Set range end at: root with replies" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save context" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        start_message_id: "root with replies",
        end_message_id: "root with replies",
        excluded_message_ids: [],
        source_conversation_id: "source-room",
      }),
    );
  });
});
