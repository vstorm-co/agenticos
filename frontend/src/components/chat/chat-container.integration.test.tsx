import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { messageOf } from "./composer-editor";
import { ChatContainer } from "./chat-container";
import { apiClient } from "@/lib/api-client";
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
  socket: { onMessage: null as ((event: MessageEvent) => void) | null, send: vi.fn() },
}));
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (options: { onMessage?: (event: MessageEvent) => void }) => {
    socket.onMessage = options.onMessage ?? null;
    return { isConnected: true, connect: vi.fn(), disconnect: vi.fn(), sendMessage: socket.send };
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
    // In the background, whose panel outlives the turn - one that answered in
    // the turn is its step once the turn is over, and would leave nothing here
    // for the switch to clear.
    mode: "async",
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

// How long a wait in this file gives the container to settle. The whole container
// mounts here - queries, stores, the socket - and on the CI runner, which runs every
// suite with coverage at once, a step that takes 76 ms locally has taken over a
// second: three different tests here failed only there, each inside the 1 s default.
// It lengthens only the wait before a real failure is reported; nothing asserted
// changes. Set once for the file, which vitest runs in modules of its own.
const SETTLE = { timeout: 5000 };
beforeAll(() => configure({ asyncUtilTimeout: SETTLE.timeout }));

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom keeps the address between the tests of a file, and the container opens
  // whatever `?id=` names: a test that created a conversation left `?id=c-new`,
  // and the next one's thread was switched to it before its listing arrived -
  // a flake that only the CI runner was slow enough to show.
  window.history.replaceState(null, "", "/");
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
  it("holds a question until the test panel's draft has saved", async () => {
    // Codex on #2062: a draft test runs what is stored, so one sent mid-save
    // tested the previous spec.
    socket.send.mockClear();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const at = (holdSending: boolean) => (
      <QueryClientProvider client={client}>
        <ChatContainer prompt={{ id: 1, text: "Refunds?" }} holdSending={holdSending} />
      </QueryClientProvider>
    );
    const { rerender } = render(at(true));
    await act(async () => {});
    const asked = () =>
      socket.send.mock.calls.filter(([frame]) => JSON.stringify(frame).includes("Refunds?"));
    expect(asked()).toHaveLength(0);

    rerender(at(false));
    await act(async () => {});
    expect(asked()).toHaveLength(1);
  });

  it("sends a pick made while the draft saved once it has", async () => {
    socket.send.mockClear();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const at = (holdSending: boolean) => (
      <QueryClientProvider client={client}>
        <ChatContainer
          holdSending={holdSending}
          emptyState={(onPick) => (
            <button type="button" onClick={() => onPick("Who are you?")}>
              pick
            </button>
          )}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(at(true));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "pick" }));
    const asked = () =>
      socket.send.mock.calls.filter(([frame]) => JSON.stringify(frame).includes("Who are you?"));
    expect(asked()).toHaveLength(0);

    rerender(at(false));
    await act(async () => {});
    expect(asked()).toHaveLength(1);
  });

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
    expect(await screen.findByText("Quarterly report researcher")).toBeInTheDocument();
    expect(screen.getByText("$0.0042")).toBeInTheDocument();

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-b");
    });

    expect(screen.queryByText("Quarterly report researcher")).not.toBeInTheDocument();
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

    expect(await screen.findByText("Quarterly report researcher")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Quarterly report researcher/ }));
    expect(screen.getByText("read the three filings and list what changed")).toBeInTheDocument();
  });
});

describe("the chat container - where an empty conversation is scrolled", () => {
  it("holds a welcome at its top and follows the foot once a turn starts", async () => {
    // In the Architect's narrow window the welcome is taller than the pane, and
    // following the foot of an empty conversation scrolled its greeting and the
    // face above it out of view.
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    mount();
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 });
    expect(scrollTo).not.toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));

    act(() =>
      useChatStore
        .getState()
        .addMessage({ id: "m-1", role: "user", content: "Hi.", timestamp: new Date() }),
    );

    // Queried again on every attempt rather than held: on CI the node found first
    // was detached by the time it was asserted on (230 ms, well inside the
    // timeout), so what is checked is the message on screen, not one node.
    await waitFor(() => expect(screen.getByText("Hi.")).toBeInTheDocument());
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
    scrollTo.mockRestore();
  });
});

describe("the chat container - who a reopened thread is addressed to", () => {
  /** Two threads, each had with one agent, as the listing reports them. */
  function listThreads() {
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({
            items: [
              { id: "c-fin", title: "Revenue", agents: [{ id: "a-fin", name: "Finance Analyst" }] },
              { id: "c-sup", title: "Refund", agents: [{ id: "a-sup", name: "Support Desk" }] },
            ],
            total: 2,
          })
        : base(url),
    );
  }

  it("addresses the composer to the agent the opened thread was had with", async () => {
    // The report: open a Finance Analyst thread with the Architect picked last,
    // and the composer said Architect - the next message would have gone to it.
    listThreads();
    useAgentSelectionStore.setState({ selectedAgentId: "a-architect" });
    useConversationStore.getState().setCurrentConversationId("c-fin");
    mount();

    await vi.waitFor(
      () => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-fin"),
      SETTLE,
    );

    act(() => useConversationStore.getState().setCurrentConversationId("c-sup"));
    await vi.waitFor(
      () => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-sup"),
      SETTLE,
    );
  });

  it("addresses a thread several agents answered to the one that answered last", async () => {
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({
            items: [
              {
                id: "c-both",
                title: "Revenue, then a customer email",
                agents: [
                  { id: "a-fin", name: "Finance Analyst" },
                  { id: "a-sup", name: "Support Desk" },
                ],
              },
            ],
            total: 1,
          })
        : base(url),
    );
    useAgentSelectionStore.setState({ selectedAgentId: "a-architect" });
    useConversationStore.getState().setCurrentConversationId("c-both");
    // The transcript as the page loads it, the last answer the Support Desk's.
    useConversationStore.getState().setCurrentMessages([
      {
        id: "m2",
        conversation_id: "c-both",
        role: "assistant",
        content: "Here",
        created_at: "2026-10-14T10:00:00Z",
        agent_id: "a-fin",
      },
      {
        id: "m4",
        conversation_id: "c-both",
        role: "assistant",
        content: "Done",
        created_at: "2026-10-14T10:05:00Z",
        agent_id: "a-sup",
      },
    ] as never);
    mount();

    await vi.waitFor(
      () => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-sup"),
      SETTLE,
    );
  });

  it("leaves a deliberate switch inside the thread alone", async () => {
    listThreads();
    useConversationStore.getState().setCurrentConversationId("c-fin");
    mount();
    await vi.waitFor(
      () => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-fin"),
      SETTLE,
    );

    act(() => useAgentSelectionStore.getState().select("a-sup"));
    // A later listing of the same thread - a turn saved, a refetch - must not
    // take the composer back from the agent somebody just chose.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-sup");
  });
});

describe("the chat container - an answer still being written after its person left", () => {
  // #2108: the question was asked, the tab closed, and the page opened again
  // while the server was still answering it.
  const LEFT = "c-left";
  let running: string | null;
  // How many reads of the transcript still find only the question.
  let unsaved: number;

  beforeEach(() => {
    running = new Date(Date.now() - 30_000).toISOString();
    unsaved = Number.POSITIVE_INFINITY;
    window.history.replaceState(null, "", `/chat?id=${LEFT}`);
    const answered = vi.fn();
    get.mockImplementation((url: string) => {
      if (url.startsWith("/auth/me")) return Promise.resolve({ ...SIGNED_IN, access_token: "t-1" });
      if (url === "/me/permissions")
        return Promise.resolve({
          organization_id: "org-1",
          role: "member",
          is_app_admin: false,
          permissions: [],
        });
      if (url.startsWith("/conversations?"))
        return Promise.resolve({
          items: [
            {
              id: LEFT,
              title: "A rollout plan",
              created_at: new Date().toISOString(),
              updated_at: null,
              is_archived: false,
              running_since: running,
            },
          ],
          total: 1,
        });
      if (url === `/conversations/${LEFT}/messages`) {
        answered();
        const question = {
          id: "m-1",
          conversation_id: LEFT,
          role: "user",
          content: "Write me a rollout plan",
          created_at: new Date().toISOString(),
        };
        const answer = {
          id: "m-2",
          conversation_id: LEFT,
          role: "assistant",
          content: "Here is the rollout plan",
          created_at: new Date().toISOString(),
        };
        const items = unsaved-- > 0 ? [question] : [question, answer];
        return Promise.resolve({ items, total: items.length, cost: null });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("says the agent is still answering, and fetches the answer when its run ends", async () => {
    // The thread as a reload finds it: the question, and nothing after it.
    useConversationStore.getState().setCurrentConversationId(LEFT);
    useConversationStore.getState().setCurrentMessages([
      {
        id: "m-1",
        conversation_id: LEFT,
        role: "user",
        content: "Write me a rollout plan",
        created_at: new Date().toISOString(),
      },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/still answering when you left/)).toBeInTheDocument();
    const reads = () => get.mock.calls.filter(([url]) => url === `/conversations/${LEFT}/messages`);
    const before = reads().length;

    // The run ends: the next read of the list no longer says it is at work.
    running = null;
    await act(async () => {
      await client.invalidateQueries();
    });

    await vi.waitFor(() => expect(reads().length).toBeGreaterThan(before), SETTLE);
  });

  it("says the opened chat was seen, though nothing in it was unread", async () => {
    // A project chat lists who has seen it, and a teammate's chat never reads as
    // unread to anyone but its owner - so opening it has to count by itself.
    useConversationStore.getState().setCurrentConversationId(LEFT);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChatContainer />
      </QueryClientProvider>,
    );

    await vi.waitFor(
      () => expect(apiClient.post).toHaveBeenCalledWith(`/conversations/${LEFT}/read`, {}),
      SETTLE,
    );
  });

  it("reads again until the answer is there, when the run ended before it was saved", async () => {
    // The run's terminal event goes out when its row commits; the answer is
    // written after that, so the first read can still end in the question.
    useConversationStore.getState().setCurrentConversationId(LEFT);
    useConversationStore.getState().setCurrentMessages([
      {
        id: "m-1",
        conversation_id: LEFT,
        role: "user",
        content: "Write me a rollout plan",
        created_at: new Date().toISOString(),
      },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/still answering when you left/)).toBeInTheDocument();

    running = null;
    unsaved = 1;
    await act(async () => {
      await client.invalidateQueries();
    });

    expect(await screen.findByText("Here is the rollout plan", {}, SETTLE)).toBeInTheDocument();
  });
});

describe("the chat container - @-mentions (#2189)", () => {
  it("sends what was picked with the message and draws it on the question", async () => {
    // Found live: the composer held the chip, and the container's send dropped it.
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/agents/a-chief/mentionables"
        ? Promise.resolve({
            items: [{ kind: "agent", id: "a-fin", name: "Finance Analyst" }],
            total: 1,
          })
        : base(url),
    );
    useAgentSelectionStore.setState({ selectedAgentId: "a-chief" });
    socket.send.mockClear();
    mount();

    const box = screen.getByRole("textbox");
    await userEvent.type(box, "Ask @fin");
    const option = await screen.findByRole("option", { name: /Finance Analyst/ });
    fireEvent.mouseDown(option);
    expect(messageOf(box)).toBe("Ask @Finance Analyst ");
    await userEvent.type(box, "about margins");
    fireEvent.submit(box.closest("form")!);

    const sent = socket.send.mock.calls.map(([frame]) => frame as Record<string, unknown>);
    const turn = sent.find((frame) => frame.message === "Ask @Finance Analyst about margins");
    expect(turn?.mentions).toEqual([{ kind: "agent", id: "a-fin" }]);
    // On the question, where it was written.
    expect(await screen.findByTitle("Finance Analyst")).toBeInTheDocument();
  });
});
