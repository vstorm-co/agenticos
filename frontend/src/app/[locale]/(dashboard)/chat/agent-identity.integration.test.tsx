/**
 * Who you are talking to, on the conversation you have just started.
 *
 * Through the page rather than either half of it, because the defect was the
 * seam: `ChatContainer` learns the new conversation's id over the socket and
 * `ConversationSidebar` draws the row, and which agent answered in a thread is
 * derived server-side from the turns stored in it. The listing was therefore
 * fetched at the one moment the answer was guaranteed to be "nobody", and
 * nothing asked again - so the agent's face appeared on the next full page load
 * and not before.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "./page";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { socket } = vi.hoisted(() => ({
  socket: { onMessage: null as ((event: MessageEvent) => void) | null },
}));
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (options: { onMessage?: (event: MessageEvent) => void }) => {
    socket.onMessage = options.onMessage ?? null;
    return { isConnected: true, connect: vi.fn(), disconnect: vi.fn(), sendMessage: vi.fn() };
  },
}));

/** Replay one server frame onto the mounted page, the way the socket would. */
function receive(type: string, data: Record<string, unknown>): void {
  act(() =>
    socket.onMessage?.(new MessageEvent("message", { data: JSON.stringify({ type, data }) })),
  );
}

const SIGNED_IN = { id: "u-1", email: "kacper@example.test", full_name: "Kacper" };
const AGENT = { id: "a-1", slug: "jarvis", name: "Jarvis", has_avatar: false };

/** Whether the first answer has been written yet - which is what the row knows. */
let answered = false;

function conversationRow() {
  return {
    id: "c-new",
    title: "hej",
    created_at: "2026-08-18T10:00:00Z",
    updated_at: "2026-08-18T10:00:00Z",
    is_archived: false,
    agents: answered ? [AGENT] : [],
  };
}

/** Every conversation listing requested so far, newest last. */
function listRequests(): string[] {
  return get.mock.calls
    .map(([path]) => path as string)
    .filter((path) => path.startsWith("/conversations?"));
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  answered = false;
  window.history.replaceState({}, "", "/chat");
  get.mockImplementation((url: string) => {
    if (url.startsWith("/auth/me")) {
      return Promise.resolve({ ...SIGNED_IN, access_token: "t-1" });
    }
    if (url === "/me/permissions") {
      return Promise.resolve({
        organization_id: "org-1",
        role: "member",
        is_app_admin: false,
        permissions: [],
      });
    }
    if (url.startsWith("/conversations?")) {
      return Promise.resolve({ items: [conversationRow()], total: 1 });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
  useAuthStore.setState({
    accessToken: "t-1",
    user: SIGNED_IN as never,
    sessionOwnerId: SIGNED_IN.id,
  });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
});

describe("the agent a new conversation is with", () => {
  it("appears as soon as the first answer is stored, with no reload", async () => {
    mount();
    // The first turn names the conversation mid-stream. The listing this pulls
    // cannot carry an agent: the answer is still being written.
    receive("conversation_created", { conversation_id: "c-new" });
    await waitFor(() => expect(screen.getAllByText("hej").length).toBeGreaterThan(0));
    expect(screen.queryByTitle("Jarvis")).not.toBeInTheDocument();

    // The turn reaches the database - the row now has an agent on it - and the
    // socket says so.
    answered = true;
    receive("message_saved", { message_id: "m-1", conversation_id: "c-new" });

    expect((await screen.findAllByTitle("Jarvis")).length).toBeGreaterThan(0);
  });

  it("asks the server rather than deciding for itself who answered", async () => {
    // The client knows which agent the turn was addressed to, and could write
    // that onto the cached row. It must not: which agents took part is the
    // server's answer, and a thread that switched agents mid-way has more than
    // one of them.
    mount();
    receive("conversation_created", { conversation_id: "c-new" });
    await waitFor(() => expect(listRequests().length).toBeGreaterThan(0));
    const before = listRequests().length;

    receive("message_saved", { message_id: "m-1", conversation_id: "c-new" });

    await waitFor(() => expect(listRequests().length).toBeGreaterThan(before));
  });
});
