import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextCandidateMessage,
  RoomThreadContextRead,
} from "@/types/room-thread-context";
import { RoomThreadContextPanel } from "./room-thread-context-panel";

const mocks = vi.hoisted(() => ({
  actions: {
    createFromRange: vi.fn(),
    updateContext: vi.fn(),
    moveContext: vi.fn(),
    returnContext: vi.fn(),
    isPending: false,
    isCurrent: vi.fn(() => true),
  },
  candidates: { data: undefined as unknown, isError: false, isPending: false, error: null },
  source: {
    messages: [] as RoomThreadContextCandidateMessage[],
    isPending: false,
    isError: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
  },
  sourceConversation: { data: { title: "Room A" }, isError: false, isPending: false },
  search: {
    items: [],
    isError: false,
    isFetching: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  },
}));

vi.mock("@/hooks/use-room-thread-context", () => ({
  useRoomThreadContextActions: () => mocks.actions,
  useRoomThreadContextCandidates: () => mocks.candidates,
  useRoomThreadContextSource: () => mocks.source,
  useRoomThreadContextSourceConversation: () => mocks.sourceConversation,
  useRoomThreadContextConversationSearch: () => mocks.search,
}));

function staleContext(moved: boolean): RoomThreadContextRead {
  return {
    source_conversation_id: "room-a",
    start_message_id: "deleted-start",
    end_message_id: "deleted-end",
    first_ordinal: 18,
    last_ordinal: 19,
    excluded_message_ids: [],
    message_ids: ["deleted-start", "deleted-end"],
    message_count: 2,
    moved,
    revision: 4,
    stale: true,
  };
}

function actionRead(context: RoomThreadContextRead): RoomThreadContextActionRead {
  return {
    conversation_id: "room-a",
    root_message_id: "thread-root",
    state: "open",
    following: false,
    unread: 0,
    can_manage: true,
    context,
  };
}

const candidates: RoomThreadContextCandidateMessage[] = [
  {
    id: "replacement-one",
    conversation_id: "room-a",
    role: "user",
    content: "First available message",
    created_at: "2026-11-01T00:00:00Z",
    ordinal: 20,
  },
  {
    id: "replacement-two",
    conversation_id: "room-a",
    role: "assistant",
    content: "Second available message",
    created_at: "2026-11-01T00:00:01Z",
    ordinal: 21,
  },
];

function panel(context: RoomThreadContextRead, threadTitle = "Thread title") {
  return (
    <RoomThreadContextPanel
      mode="thread"
      destinationConversationId="room-a"
      destinationTitle="Room A"
      rootMessageId="thread-root"
      threadTitle={threadTitle}
      context={context}
      canManage
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.candidates.data = {
    source_conversation_id: "room-a",
    items: candidates,
    total: candidates.length,
  };
  mocks.actions.updateContext.mockResolvedValue(
    actionRead({ ...staleContext(true), stale: false }),
  );
});

describe("RoomThreadContextPanel stale context repair", () => {
  it("anchors Select context for the optional room tour stop", () => {
    render(
      <RoomThreadContextPanel
        mode="create"
        destinationConversationId="room-a"
        destinationTitle="Room A"
      />,
    );

    expect(screen.getByRole("button", { name: "Select context" })).toHaveAttribute(
      "data-tour",
      "chat-room-thread-context",
    );
  });

  it("keeps return disabled and lets a manager save a replacement range without a title", async () => {
    const stale = staleContext(true);
    const view = render(panel(stale));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Some saved messages are no longer available",
    );
    expect(screen.getByText("2 messages included")).toBeInTheDocument();
    expect(screen.queryByText(/Messages 18/)).toBeNull();
    expect(screen.getByRole("button", { name: "Return to room" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Edit context" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Set range start at: First available message" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Set range end at: First available message" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save context" }));

    await waitFor(() =>
      expect(mocks.actions.updateContext).toHaveBeenCalledWith({
        start_message_id: "replacement-one",
        end_message_id: "replacement-one",
        excluded_message_ids: [],
        source_conversation_id: "room-a",
        expected_context_revision: 4,
      }),
    );
    expect(mocks.actions.updateContext.mock.calls[0]?.[0]).not.toHaveProperty("title");

    const repaired = { ...stale, revision: 5, stale: false };
    view.rerender(panel(repaired));
    await waitFor(() => {
      expect(screen.queryByText(/Some saved messages are no longer available/)).toBeNull();
      expect(screen.getByRole("button", { name: "Return to room" })).toBeEnabled();
    });
  });

  it("keeps move disabled while an unmoved snapshot is stale", () => {
    render(panel(staleContext(false)));
    expect(screen.getByRole("button", { name: "Move into thread" })).toBeDisabled();
  });
});
