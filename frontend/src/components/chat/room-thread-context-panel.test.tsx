import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextCandidateMessage,
  RoomThreadContextRead,
} from "@/types/room-thread-context";
import { RoomThreadContextPanel } from "./room-thread-context-panel";
import { ApiError } from "@/lib/api-error";

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

const current: RoomThreadContextRead = { ...staleContext(false), stale: false };
const click = (name: string) => userEvent.click(screen.getByRole("button", { name }));

function thread(context: RoomThreadContextRead | null, props: Record<string, unknown> = {}) {
  return (
    <RoomThreadContextPanel
      mode="thread"
      destinationConversationId="room-a"
      destinationTitle="Room A"
      rootMessageId="thread-root"
      context={context}
      canManage
      {...props}
    />
  );
}

async function chooseRange() {
  await click("Set range start at: First available message");
  await click("Set range end at: Second available message");
}

describe("RoomThreadContextPanel creating a thread", () => {
  const onCreated = vi.fn();
  const create = () => (
    <RoomThreadContextPanel
      mode="create"
      destinationConversationId="room-a"
      destinationTitle="Room A"
      onCreated={onCreated}
    />
  );

  beforeEach(() => {
    mocks.source.messages = candidates;
    mocks.actions.isCurrent.mockReturnValue(true);
  });

  it("opens the editor, creates the thread and reports its root", async () => {
    mocks.actions.createFromRange.mockResolvedValue(actionRead(current));
    render(create());
    await click("Select context");
    await chooseRange();
    await click("Create thread marker");

    await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith("thread-root"));
    expect(screen.getByRole("button", { name: "Select context" })).toBeInTheDocument();
  });

  it("keeps the editor open when nothing current came back, and reports a failure", async () => {
    mocks.actions.createFromRange.mockResolvedValueOnce(null);
    render(create());
    await click("Select context");
    await chooseRange();
    await click("Create thread marker");
    expect(onCreated).not.toHaveBeenCalled();

    mocks.actions.createFromRange.mockRejectedValueOnce(new Error("boom"));
    await click("Create thread marker");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Cancel" })[0]!);
    expect(screen.getByRole("button", { name: "Select context" })).toBeInTheDocument();
  });

  it("pages the source and forgets an error when another source is picked", async () => {
    mocks.source.hasNextPage = true;
    mocks.search.items = [{ id: "room-b", title: "Room B" }] as never;
    mocks.actions.createFromRange.mockRejectedValueOnce(new Error("boom"));
    render(create());
    await click("Select context");
    await click("Load earlier messages");
    expect(mocks.source.fetchNextPage).toHaveBeenCalled();
    await chooseRange();
    await click("Create thread marker");
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await click("Choose source conversation");
    await userEvent.type(screen.getByRole("searchbox"), "Room");
    await userEvent.click(await screen.findByRole("option", { name: /Room B/ }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/from Room B/)).toBeInTheDocument();
    mocks.source.hasNextPage = false;
    mocks.search.items = [];
  });
});

describe("RoomThreadContextPanel managing a thread", () => {
  beforeEach(() => {
    mocks.actions.isCurrent.mockReturnValue(true);
    mocks.source.messages = [];
  });

  it("renders nothing for a thread without context", () => {
    const { container } = render(thread(null));
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["Move into thread", false, "moveContext", "Selected messages moved into the thread."],
    ["Return to room", true, "returnContext", "Selected messages returned to the room."],
  ] as const)("reports the outcome of %s", async (button, moved, action, notice) => {
    mocks.actions[action]
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(actionRead(current))
      .mockRejectedValueOnce(new Error("boom"));
    render(thread({ ...current, moved }));

    await click(button);
    expect(screen.queryByText(notice)).toBeNull();
    await click(button);
    expect(await screen.findByText(notice)).toBeInTheDocument();
    expect(mocks.actions[action]).toHaveBeenLastCalledWith({ expected_context_revision: 4 });
    await click(button);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it.each([
    ["room_busy", "The room is busy"],
    ["nested_replies", "includes a reply thread"],
    ["stale_context", "changed elsewhere"],
    ["archived_thread", "This thread is archived"],
    ["invalid_range", "no longer a valid range"],
    ["cross_room_move", "cannot be moved between conversations"],
    ["context_source_in_use", "Start a new thread"],
    ["something_else", "refused by the server"],
  ])("explains a %s refusal", async (reason, text) => {
    mocks.actions.moveContext.mockRejectedValueOnce(
      new ApiError(409, "refused by the server", {
        error: { code: "CONFLICT", message: "refused by the server", details: { reason } },
      }),
    );
    render(thread(current));
    await click("Move into thread");
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("saves an edit, and stays open when the result is not current", async () => {
    mocks.actions.updateContext
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(actionRead(current));
    mocks.source.messages = candidates;
    render(thread({ ...current, start_message_id: "", end_message_id: "" }));
    await click("Edit context");
    await chooseRange();
    await click("Save context");
    expect(screen.getByRole("button", { name: "Save context" })).toBeInTheDocument();
    await click("Save context");
    expect((await screen.findAllByRole("alert"))[0]).toBeInTheDocument();
    await click("Save context");
    expect(await screen.findByText("Thread context updated.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save context" })).toBeNull();
  });

  it("closes the editor from its own cancel and from the header", async () => {
    render(thread(current));
    await click("Edit context");
    await userEvent.click(screen.getAllByRole("button", { name: "Cancel" })[0]!);
    expect(screen.queryByRole("button", { name: "Save context" })).toBeNull();
    await click("Edit context");
    await userEvent.click(screen.getAllByRole("button", { name: "Cancel" }).at(-1)!);
    expect(screen.queryByRole("button", { name: "Save context" })).toBeNull();
  });

  it("warns that saving another source returns moved messages, and sends move:false", async () => {
    mocks.search.items = [{ id: "room-b", title: "Room B" }] as never;
    mocks.source.hasNextPage = true;
    mocks.source.messages = candidates.map((item) => ({ ...item, conversation_id: "room-b" }));
    mocks.actions.updateContext.mockResolvedValue(actionRead(current));
    render(thread({ ...current, moved: true }));
    await click("Edit context");
    await click("Load earlier messages");
    expect(mocks.source.fetchNextPage).toHaveBeenCalled();
    await click("Choose source conversation");
    await userEvent.type(screen.getByRole("searchbox"), "Room");
    await userEvent.click(await screen.findByRole("option", { name: /Room B/ }));
    expect(screen.getByText(/will return the current moved messages/)).toBeInTheDocument();

    await chooseRange();
    await click("Save context");

    expect(mocks.actions.updateContext).toHaveBeenCalledWith(
      expect.objectContaining({ source_conversation_id: "room-b", move: false }),
    );
    mocks.search.items = [];
    mocks.source.hasNextPage = false;
  });

  it("links a source in another conversation and offers no move", () => {
    const other = { ...current, source_conversation_id: "room b" };
    const view = render(thread(other));
    expect(screen.getByRole("link")).toHaveAttribute("href", "/chat?id=room%20b");
    expect(screen.getByRole("link")).toHaveTextContent("Open source conversation: Room A");
    expect(screen.queryByRole("button", { name: "Move into thread" })).toBeNull();

    const data = mocks.sourceConversation.data;
    mocks.sourceConversation.data = { title: "" };
    view.rerender(thread({ ...other, revision: 5 }));
    expect(screen.getByRole("link")).toHaveTextContent("Open source conversation");
    mocks.sourceConversation.data = data;
  });

  it("lists the saved messages in order", () => {
    render(
      thread(current, {
        contextMessages: [
          { id: "b", role: "assistant", content: "", ordinal: 2 },
          { id: "a", role: "user", content: "Earlier", ordinal: 1, sender: { name: "Ada" } },
        ],
      }),
    );
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "AdaEarlier",
      "Assistant messageAttachment-only message",
    ]);
  });

  it.each([
    ["a viewer", { canManage: false }],
    ["an archived thread", { threadState: "archived" }],
  ])("offers no change to %s", (_case, props) => {
    render(thread(current, props));
    expect(screen.getByText("The saved context messages are unavailable.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each(["source", "candidates"] as const)("reports a failed %s read", async (read) => {
    const target = mocks[read] as { isError: boolean };
    target.isError = true;
    render(thread(current));
    await act(async () => {
      await click("Edit context");
    });
    expect(screen.getAllByRole("alert")[0]).toBeInTheDocument();
    target.isError = false;
  });
});

describe("RoomThreadContextPanel overtaken actions", () => {
  beforeEach(() => {
    mocks.actions.isCurrent.mockReturnValue(false);
    mocks.source.messages = candidates;
  });

  it.each([
    ["Move into thread", false, "moveContext"],
    ["Return to room", true, "returnContext"],
  ] as const)("announces nothing for an overtaken %s", async (button, moved, action) => {
    mocks.actions[action].mockResolvedValueOnce(actionRead(current));
    render(thread({ ...current, moved }));
    await click(button);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps an overtaken edit open without announcing it", async () => {
    mocks.actions.updateContext.mockResolvedValueOnce(actionRead(current));
    render(thread(current));
    await click("Edit context");
    await chooseRange();
    await click("Save context");
    expect(screen.queryByText("Thread context updated.")).toBeNull();
    expect(screen.getByRole("button", { name: "Save context" })).toBeInTheDocument();
  });

  it("does not report an overtaken creation", async () => {
    const onCreated = vi.fn();
    mocks.actions.createFromRange.mockResolvedValueOnce(actionRead(current));
    render(
      <RoomThreadContextPanel
        mode="create"
        destinationConversationId="room-a"
        destinationTitle="Room A"
        onCreated={onCreated}
      />,
    );
    await click("Select context");
    await chooseRange();
    await click("Create thread marker");
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("RoomThreadContextPanel without a thread to act on", () => {
  beforeEach(() => {
    mocks.source.messages = candidates;
  });

  it.each([
    ["Move into thread", false],
    ["Return to room", true],
  ] as const)("writes nothing on %s", async (button, moved) => {
    render(thread({ ...current, moved }, { rootMessageId: null }));
    await click(button);
    expect(mocks.actions.moveContext).not.toHaveBeenCalled();
    expect(mocks.actions.returnContext).not.toHaveBeenCalled();
  });

  it("writes nothing on save", async () => {
    render(thread(current, { rootMessageId: null }));
    await click("Edit context");
    await chooseRange();
    await click("Save context");
    expect(mocks.actions.updateContext).not.toHaveBeenCalled();
  });
});
