import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatContainer } from "./chat-container";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useOrgStore,
} from "@/stores";

/**
 * The chat as a person sees it, across a conversation switch.
 *
 * Through the whole container rather than the hook, because the leak was the two
 * halves disagreeing: `useChat` retained the panels and `ChatContainer` drew
 * whatever it was handed under whichever transcript was on screen. A hook test
 * asserting on `delegations` proves the state; this proves what the reader gets.
 */

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

/** Replay one server frame onto the mounted chat, the way the socket would. */
function receive(type: string, data: Record<string, unknown>): void {
  act(() =>
    socket.onMessage?.(new MessageEvent("message", { data: JSON.stringify({ type, data }) })),
  );
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatContainer />
    </QueryClientProvider>,
  );
}

/** A delegated turn, from the delegate starting to the parent finishing. */
function runDelegatedTurn(): void {
  receive("model_request_start", {});
  receive("subagent_start", {
    kind: "subagent_start",
    task_id: "t-1",
    subagent: "quarterly-report-researcher",
    depth: 0,
    mode: "sync",
    prompt: "read the three filings and list what changed",
    parent_task_id: null,
  });
  receive("subagent_text_delta", {
    kind: "subagent_text_delta",
    task_id: "t-1",
    subagent: "quarterly-report-researcher",
    depth: 0,
    delta: "Revenue moved 4%.",
  });
  receive("subagent_complete", {
    kind: "subagent_complete",
    task_id: "t-1",
    subagent: "quarterly-report-researcher",
    depth: 0,
    status: "completed",
    run_id: "r-1",
    cost_usd: 0.0042,
    input_tokens: 900,
    output_tokens: 120,
    error: null,
  });
  receive("complete", { usage: null });
}

const SIGNED_IN = { id: "u-1", email: "kacper@example.test", full_name: "Kacper" };

beforeEach(() => {
  vi.clearAllMocks();
  // Answered per endpoint, and `/auth/me` has to answer with the account already
  // signed in: `adoptUser` empties every store when the id it gets back is not the
  // one that owns the session, which would clear the conversation - and so the
  // panels - for a reason that has nothing to do with this test.
  get.mockImplementation((url: string) =>
    url.startsWith("/auth/me")
      ? Promise.resolve({ ...SIGNED_IN, access_token: "t-1" })
      : url === "/me/permissions"
        ? // A real shape, not the list fallback: `usePermissions` reads
          // `data.permissions` off whatever this answers.
          Promise.resolve({
            organization_id: "org-1",
            role: "member",
            is_app_admin: false,
            permissions: [],
          })
        : Promise.resolve({ items: [], total: 0 }),
  );
  useAuthStore.setState({
    accessToken: "t-1",
    user: SIGNED_IN as never,
    sessionOwnerId: SIGNED_IN.id,
  });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
});

describe("the chat container - delegation panels across a conversation switch", () => {
  it("leaves one conversation's specialists behind when another is opened", async () => {
    // The report: finish a delegated turn in one conversation, then pick another from
    // the sidebar *without sending anything*. Sending was the only thing that cleared
    // the panels, so the previous thread's delegate, its brief and its cost were drawn
    // under the new thread's transcript.
    useConversationStore.getState().setCurrentConversationId("c-a");
    mount();
    runDelegatedTurn();
    // The delegate's own name and cost, not the chrome around them: every page here
    // renders its empty state when a query fails, so an assertion on a heading is an
    // assertion on nothing.
    expect(await screen.findByText("quarterly-report-researcher")).toBeInTheDocument();
    expect(screen.getByText("$0.0042")).toBeInTheDocument();

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-b");
    });

    expect(screen.queryByText("quarterly-report-researcher")).not.toBeInTheDocument();
    expect(screen.queryByText("$0.0042")).not.toBeInTheDocument();
  });

  it("keeps the panels of the turn that is still streaming when it names its conversation", async () => {
    // A first turn creates the conversation and learns the id from
    // `conversation_created` mid-stream. That is this conversation being named, not
    // another being opened, and clearing there would take the panels of the turn the
    // reader is watching.
    mount();
    receive("model_request_start", {});
    receive("subagent_start", {
      kind: "subagent_start",
      task_id: "t-1",
      subagent: "quarterly-report-researcher",
      depth: 0,
      mode: "async",
      prompt: "read the three filings and list what changed",
      parent_task_id: null,
    });

    receive("conversation_created", { conversation_id: "c-new" });

    expect(await screen.findByText("quarterly-report-researcher")).toBeInTheDocument();
    expect(screen.getByText("read the three filings and list what changed")).toBeInTheDocument();
  });
});
