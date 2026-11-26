import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConversationMessage } from "@/types/conversation";
import type { RoomThreadContextRead } from "@/types/room-thread-context";
import { RoomThreadContextRangeSelector } from "./room-thread-context-range-selector";

function message(
  id: string,
  overrides: Partial<ConversationMessage & { deleted_at: string }> = {},
): ConversationMessage {
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

describe("RoomThreadContextRangeSelector choices", () => {
  const select = (props: Record<string, unknown> = {}) => (
    <RoomThreadContextRangeSelector
      mode="create"
      sourceConversationId="source-room"
      messages={[]}
      onSubmit={vi.fn()}
      {...props}
    />
  );
  const three = [
    message("third", { ordinal: 3, role: "assistant", content: "" }),
    message("first", { ordinal: 1, sender: { name: "Ada" } as never }),
    message("second", { ordinal: 2, deleted_at: "" }),
    message("gone", { ordinal: 4, deleted_at: "2026-11-02T00:00:00Z" }),
    message("note", { ordinal: 5, role: "system" }),
  ];
  const click = (name: string) => userEvent.click(screen.getByRole("button", { name }));
  const submitForm = (container: HTMLElement) => fireEvent.submit(container.querySelector("form")!);

  it("sends a reversed range in order, with exclusions and a trimmed title", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(select({ messages: three, onSubmit, sourceTitle: "Room B" }));
    expect(screen.getByText(/from Room B/)).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Attachment-only message")).toBeInTheDocument();
    expect(screen.queryByText("gone")).toBeNull();
    expect(screen.queryByText("note")).toBeNull();

    await click("Set range start at: Assistant message");
    await click("Set range end at: first");
    await click("Exclude message: second");
    await click("Include message: second");
    await click("Exclude message: second");
    await userEvent.type(screen.getByLabelText("Thread title"), "  Topic  ");
    await click("Create thread marker");

    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      start_message_id: "first",
      end_message_id: "third",
      excluded_message_ids: ["second"],
      source_conversation_id: "source-room",
      title: "Topic",
    });
  });

  it("forgets an exclusion that falls outside the new bounds", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(select({ messages: three, onSubmit }));
    await click("Set range start at: first");
    await click("Set range end at: Assistant message");
    await click("Exclude message: second");
    await click("Set range end at: first");
    await click("Set range end at: Assistant message");
    await click("Create thread marker");

    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ excluded_message_ids: [] }),
    );
  });

  it("explains why an incomplete or empty range cannot be sent", async () => {
    const onSubmit = vi.fn();
    const { container } = render(select({ messages: [message("only")], onSubmit }));
    submitForm(container);
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a start and end message.");

    await click("Set range start at: only");
    await click("Set range end at: only");
    await click("Exclude message: only");
    submitForm(container);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Include at least one message in the range.",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  const many = Array.from({ length: 502 }, (_, index) => message(`m${index}`));
  const bounds = {
    revision: 1,
    start_message_id: "m0",
    end_message_id: "m501",
  };

  it("refuses more than five hundred messages or exclusions", () => {
    const view = render(select({ mode: "edit", messages: many, initial: bounds }));
    submitForm(view.container);
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
      "A context can include at most 500 messages.",
    );
    view.unmount();

    const excluded_message_ids = many.slice(0, 501).map((item) => item.id);
    render(select({ mode: "edit", messages: many, initial: { ...bounds, excluded_message_ids } }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A context can exclude at most 500 messages.",
    );
  });

  it("shows loading, empty, paging, saving and error states", async () => {
    const onLoadEarlier = vi.fn();
    const onCancel = vi.fn();
    const view = render(select({ isLoading: true, hasEarlier: true, onLoadEarlier, onCancel }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading source messages…");
    await click("Load earlier messages");
    await click("Cancel");
    expect(onLoadEarlier).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();

    view.rerender(
      select({
        hasEarlier: true,
        isLoadingEarlier: true,
        isSaving: true,
        error: "Refused",
        onLoadEarlier,
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "There are no eligible messages in this conversation.",
    );
    expect(screen.getByRole("button", { name: "Loading earlier messages…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Refused");
  });
});
