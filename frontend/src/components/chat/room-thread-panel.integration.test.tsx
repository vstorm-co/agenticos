import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { announceRoomChange } from "@/lib/room-events";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { ChatMessage, MessageReply } from "@/types";
import type { RoomThreadPage } from "@/types/room";
import { RoomThreadPanel } from "./room-thread-panel";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "writer",
        name: "Writer",
        slug: "writer",
        status: "published",
        can_run: true,
        visibility: "private",
        owner_user_id: "me",
        current_version_id: "v1",
        description: null,
      },
    ],
  }),
}));
vi.mock("@/hooks/use-projects", () => ({
  useProject: () => ({ project: { can_use: true }, isLoading: false }),
}));
// The message renderer has its own attribution/attachment tests. Keep its scope
// boundary visible here while exercising the real query, store and composer.
vi.mock("./message-item", () => ({
  MessageItem: ({
    message,
    threadRootPreview,
    allowReply,
    onReply,
  }: {
    message: ChatMessage;
    threadRootPreview: boolean;
    allowReply: boolean;
    onReply: (reply: MessageReply) => void;
  }) => (
    <article data-thread-root={threadRootPreview ? message.id : undefined}>
      <p>{message.content}</p>
      {allowReply && (
        <button
          onClick={() =>
            onReply({ messageId: message.id, role: message.role, excerpt: message.content })
          }
        >
          Quote original
        </button>
      )}
    </article>
  ),
}));
vi.mock("./message-list", () => ({
  MessageList: ({
    messages,
    allowReply,
    onReply,
  }: {
    messages: ChatMessage[];
    allowReply: boolean;
    onReply: (reply: MessageReply) => void;
  }) => (
    <div>
      {messages.map((message) => (
        <article key={message.id} data-message-id={message.id}>
          <p>{message.content}</p>
          {allowReply && (
            <button
              onClick={() =>
                onReply({ messageId: message.id, role: message.role, excerpt: message.content })
              }
            >
              Quote {message.id}
            </button>
          )}
        </article>
      ))}
    </div>
  ),
}));

let client: QueryClient;
let page: RoomThreadPage;
const close = vi.fn();
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const identity = {
  conversationId: "room-a",
  accountId: "me",
  tenantId: "org-a",
  selectionVersion: 3,
};
function row(id: string, root: string, content = id): ChatMessage {
  return {
    id,
    conversationId: "room-a",
    role: "user",
    content,
    timestamp: new Date(),
    threadRootMessageId: root,
  };
}
function view(rootId = "root-a", extra: { readOnly?: boolean; projectId?: string | null } = {}) {
  return (
    <RoomThreadPanel
      key={rootId}
      conversationId="room-a"
      projectId="project-a"
      rootId={rootId}
      readOnly={false}
      onClose={close}
      onTyping={vi.fn()}
      isProcessing={false}
      {...extra}
    />
  );
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function changed() {
  act(() =>
    announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" }),
  );
}
function serve(path: string) {
  if (path === "/orgs") return { items: [] };
  if (path.includes("room-threads")) return page;
  return { items: [], total: 0, can_post: true };
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  useAuthStore.setState({
    user: {
      id: "me",
      email: "me@example.com",
      is_active: true,
      created_at: "2026-11-14T00:00:00Z",
    },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a", selectionVersion: 3 });
  useChatStore.setState({
    messages: [],
    loadedTranscript: identity,
    roomDrafts: {},
    replyTo: null,
  });
  page = {
    root: {
      id: "root-a",
      conversation_id: "room-a",
      role: "user",
      content: "Original topic",
      created_at: "2026-11-14T00:00:00Z",
    },
    items: [
      {
        id: "reply-a",
        conversation_id: "room-a",
        role: "user",
        content: "Saved reply A",
        created_at: "2026-11-14T00:00:01Z",
        thread_root_message_id: "root-a",
      },
    ],
    total: 1,
    can_post: true,
  };
  vi.mocked(apiClient.get).mockImplementation(async (path) => serve(String(path)));
  vi.mocked(apiClient.post).mockResolvedValue({ message: page.items[0], request: null });
});
afterEach(() => client.clear());

describe("RoomThreadPanel", () => {
  it("admits live rows only after a fresh scoped authorization and excludes main/other-root rows", async () => {
    const pending = deferred<RoomThreadPage>();
    useChatStore.setState({
      messages: [
        { ...row("main", "unused", "Main room"), threadRootMessageId: undefined },
        { ...row("live-a", "root-a", "Live A"), role: "assistant", isStreaming: true },
        row("reply-b", "root-b", "Other thread B"),
      ],
    });
    vi.mocked(apiClient.get).mockImplementation((path) =>
      String(path).includes("room-threads")
        ? pending.promise
        : Promise.resolve(serve(String(path))),
    );
    render(view(), { wrapper });
    expect(screen.getByRole("status")).toHaveTextContent("Loading thread");
    expect(screen.queryByText("Live A")).not.toBeInTheDocument();
    await act(async () => pending.resolve(page));
    expect(await screen.findByText("Saved reply A")).toBeInTheDocument();
    expect(screen.getByText("Live A")).toBeInTheDocument();
    expect(screen.queryByText("Other thread B")).not.toBeInTheDocument();
    expect(screen.queryByText("Main room")).not.toBeInTheDocument();
    expect(document.querySelector("[data-thread-root]")).toHaveAttribute(
      "data-thread-root",
      "root-a",
    );
  });

  it("quotes the root into the thread composer and posts with both identities", async () => {
    render(view(), { wrapper });
    await screen.findByRole("textbox", { name: "Reply to thread" });
    await userEvent.click(screen.getByRole("button", { name: "Quote original" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Reply to thread" }), "A reply here");
    await userEvent.click(screen.getByRole("button", { name: "Post reply" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({
          content: "A reply here",
          thread_root_message_id: "root-a",
          reply_to_message_id: "root-a",
        }),
      ),
    );
    expect(useChatStore.getState().replyTo).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close thread" }));
    expect(close).toHaveBeenCalledOnce();
  });

  it.each([{ readOnly: true }, { projectId: null }])(
    "keeps authorized history read-only (%j)",
    async (extra) => {
      render(view("root-a", extra), { wrapper });
      expect(await screen.findByText("Saved reply A")).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Reply to thread" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Quote original" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Quote reply-a" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Close thread" })).toBeEnabled();
    },
  );

  it("hides posting controls when the thread authorization becomes read-only", async () => {
    render(view(), { wrapper });
    await screen.findByRole("textbox", { name: "Reply to thread" });
    page = { ...page, can_post: false };
    changed();
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Reply to thread" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Saved reply A")).toBeInTheDocument();
  });

  it("removes cached content and live rows after access is rejected, then retries the read", async () => {
    render(view(), { wrapper });
    await screen.findByText("Saved reply A");
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (String(path).includes("room-threads")) throw new ApiError(403, "Access changed");
      return serve(String(path));
    });
    changed();
    await screen.findByRole("alert");
    expect(screen.queryByText("Original topic")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved reply A")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockImplementation(async (path) => serve(String(path)));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Saved reply A")).toBeInTheDocument();
  });

  it("does not reuse a cached grant when a thread is closed and reopened", async () => {
    const first = render(view(), { wrapper });
    await screen.findByText("Saved reply A");
    first.unmount();
    const pending = deferred<RoomThreadPage>();
    vi.mocked(apiClient.get).mockImplementation((path) =>
      String(path).includes("room-threads")
        ? pending.promise
        : Promise.resolve(serve(String(path))),
    );
    render(view(), { wrapper });
    expect(screen.queryByText("Saved reply A")).not.toBeInTheDocument();
    await act(async () => pending.reject(new ApiError(404, "No thread")));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("does not merge old tenant or selection rows into a freshly authorized view", async () => {
    useChatStore.setState({
      messages: [row("old", "root-a", "Old identity")],
      loadedTranscript: { ...identity, tenantId: "old-tenant" },
    });
    render(view(), { wrapper });
    await screen.findByText("Original topic");
    expect(screen.queryByText("Old identity")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved reply A")).not.toBeInTheDocument();
    act(() => useChatStore.setState({ messages: [], loadedTranscript: identity }));
    expect(await screen.findByText("Saved reply A")).toBeInTheDocument();
  });

  it("removes authorized thread content immediately when the account is cleared", async () => {
    render(view(), { wrapper });
    await screen.findByText("Saved reply A");
    await screen.findByRole("textbox", { name: "Reply to thread" });
    act(() => useAuthStore.setState({ user: null }));
    expect(screen.queryByText("Original topic")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved reply A")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading thread");
  });

  it("loads earlier replies in order and preserves the reader's place without fetching main history", async () => {
    page = { ...page, total: 2 };
    const pending = deferred<RoomThreadPage>();
    vi.mocked(apiClient.get).mockImplementation((path) =>
      String(path).includes("before=reply-a")
        ? pending.promise
        : Promise.resolve(serve(String(path))),
    );
    const { container } = render(view(), { wrapper });
    await screen.findByText("Saved reply A");
    const scroller = container.querySelector<HTMLDivElement>(".overflow-y-auto")!;
    let height = 700;
    Object.defineProperties(scroller, {
      scrollHeight: { get: () => height },
      clientHeight: { value: 200 },
    });
    scroller.scrollTop = 300;
    fireEvent.scroll(scroller);
    await userEvent.click(screen.getByRole("button", { name: "Load earlier replies" }));
    expect(screen.getByRole("button", { name: "Load earlier replies" })).toBeDisabled();
    await act(async () => {
      height = 900;
      pending.resolve({
        ...page,
        items: [{ ...page.items[0]!, id: "earlier", content: "Earlier reply" }],
      });
    });
    await screen.findByText("Earlier reply");
    await waitFor(() => expect(scroller.scrollTop).toBe(500));
    const replies = [...container.querySelectorAll("[data-message-id]")].map((element) =>
      element.getAttribute("data-message-id"),
    );
    expect(replies).toEqual(["earlier", "reply-a"]);
    expect(screen.queryByRole("button", { name: "Load earlier replies" })).not.toBeInTheDocument();
    expect(
      vi.mocked(apiClient.get).mock.calls.some(([path]) => String(path).includes("/messages?")),
    ).toBe(false);
  });

  it("ignores an earlier-page scroll restoration after the reader opens another thread", async () => {
    page = { ...page, total: 2 };
    const earlierPage = {
      ...page,
      items: [{ ...page.items[0]!, id: "earlier", content: "Earlier reply" }],
    };
    const pending = deferred<RoomThreadPage>();
    vi.mocked(apiClient.get).mockImplementation((path) =>
      String(path).includes("before=reply-a")
        ? pending.promise
        : Promise.resolve(serve(String(path))),
    );
    const mounted = render(view(), { wrapper });
    await screen.findByText("Saved reply A");
    const original = mounted.container.querySelector<HTMLDivElement>(".overflow-y-auto")!;
    let height = 700;
    Object.defineProperties(original, {
      scrollHeight: { get: () => height },
      clientHeight: { value: 200 },
    });
    original.scrollTop = 300;
    fireEvent.scroll(original);
    await userEvent.click(screen.getByRole("button", { name: "Load earlier replies" }));
    page = {
      ...page,
      root: { ...page.root, id: "root-b", content: "Another topic" },
      items: [
        {
          ...page.items[0]!,
          id: "reply-b",
          content: "Saved reply B",
          thread_root_message_id: "root-b",
        },
      ],
      total: 1,
    };
    mounted.rerender(view("root-b"));
    await screen.findByText("Saved reply B");
    const current = mounted.container.querySelector<HTMLDivElement>(".overflow-y-auto")!;
    current.scrollTop = 80;
    await act(async () => {
      height = 900;
      pending.resolve(earlierPage);
    });
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });
    expect(original.isConnected).toBe(false);
    expect(original.scrollTop).toBe(300);
    expect(current.scrollTop).toBe(80);
    expect(screen.queryByText("Earlier reply")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved reply A")).not.toBeInTheDocument();
  });

  it("shows an empty thread, its scoped action, and preserves its draft after switching away", async () => {
    page = { ...page, items: [], total: 0 };
    const mounted = render(
      <RoomThreadPanel
        conversationId="room-a"
        projectId="project-a"
        rootId="root-a"
        readOnly={false}
        onClose={close}
        onTyping={vi.fn()}
        isProcessing={false}
        actions={(readOnly) => <button disabled={readOnly}>Thread approval</button>}
      />,
      { wrapper },
    );
    await screen.findByText("Start the conversation in this thread.");
    expect(
      within(screen.getByRole("complementary", { name: "Thread" })).getByRole("button", {
        name: "Thread approval",
      }),
    ).toBeInTheDocument();
    await userEvent.type(
      await screen.findByRole("textbox", { name: "Reply to thread" }),
      "A stays",
    );
    page = { ...page, root: { ...page.root, id: "root-b", content: "B topic" } };
    mounted.rerender(view("root-b"));
    await screen.findByText("B topic");
    expect(await screen.findByRole("textbox", { name: "Reply to thread" })).toHaveValue("");
    page = { ...page, root: { ...page.root, id: "root-a", content: "Original topic" } };
    mounted.rerender(view());
    await screen.findByText("Original topic");
    expect(await screen.findByRole("textbox", { name: "Reply to thread" })).toHaveValue("A stays");
  });
});
