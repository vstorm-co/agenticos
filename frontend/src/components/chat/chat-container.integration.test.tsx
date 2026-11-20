import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  configure,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { announceChange } from "@/lib/live-updates";
import type { ChangeEvent } from "@/types/change-events";
import { messageOf } from "./composer-editor";
import { ChatContainer } from "./chat-container";
import type { AssistantPageContext } from "@/lib/assistant-page-context";
import { apiClient } from "@/lib/api-client";
import { useConversations } from "@/hooks/use-conversations";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { Project } from "@/types/projects";
import type { ConversationCost, ConversationMessage } from "@/types";
import type { ConversationForkRead } from "@/lib/conversation-forks-api";
import type { ConversationMessageSearchTarget } from "@/lib/conversation-message-search-api";
import type { RoomParticipantRead } from "@/types/room";
import { qk } from "@/lib/query-keys";
import { initialCall } from "@/lib/voice/call-reducer";
import { useChatControlsStore, currentChatControlScope } from "@/stores/chat-controls-store";
import {
  useAgentSelectionStore,
  useAuthStore,
  useBrowserPanelStore,
  useChatStore,
  useWorkingStore,
  useComposerIntentStore,
  useConversationStore,
  useOrgStore,
} from "@/stores";
import { TeamRoomComposer } from "./team-room-composer";

/**
 * The chat as a person sees it, across a conversation switch.
 *
 * Through the whole container rather than the hook, because the leak was the two
 * halves disagreeing: `useChat` retained the panels and `ChatContainer` drew
 * whatever it was handed under whichever transcript was on screen. A hook test
 * asserting on `delegations` proves the state; this proves what the reader gets.
 */

const { get, upload, routerPush } = vi.hoisted(() => ({
  get: vi.fn(),
  upload: vi.fn(async () => ({ text: "hello" })),
  routerPush: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), upload, patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/locale-navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/locale-navigation")>()),
  useRouter: () => ({ push: routerPush }),
}));

/**
 * The recording, as a phase this test sets; and the glow, as attributes. What is
 * under test is what the container hands the glow and the strip for a phase, not
 * the recorder (`use-dictation.test.ts`) or the beam (`voice-glow`).
 */
const dictation = vi.hoisted(() => ({
  phase: "idle" as string,
  reason: null as string | null,
  upload: null as number | null,
  inserted: false,
  /** The recorder's cancel, one for every render, as the hook's own is. */
  cancel: vi.fn(),
  /** The recorder's start, which the microphone - or a shortcut - presses. */
  start: vi.fn(),
  /** The format the container last handed the recorder. */
  format: undefined as string | undefined,
  /** Where the container last told the recorder to send a recording. */
  send: undefined as
    | ((
        recording: Blob,
        seconds: number,
        signal: AbortSignal,
        onProgress: (fraction: number) => void,
      ) => unknown)
    | null
    | undefined,
}));
vi.mock("@/hooks/use-dictation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-dictation")>()),
  useDictation: ({ format, send }: { format: string; send: typeof dictation.send }) => {
    dictation.format = format;
    dictation.send = send;
    return {
      state: {
        phase: dictation.phase,
        elapsed: 42,
        remaining: null,
        silent: false,
        meter: { read: () => 0, subscribe: () => () => {} },
        reason: dictation.reason,
        canRetry: dictation.reason !== null,
        retryAfter: null,
        transcript: dictation.inserted ? { id: 1, text: "hello there" } : null,
        upload: dictation.upload,
        stoppedAtLimit: false,
        inserted: dictation.inserted,
      },
      actions: {
        start: dictation.start,
        stop: vi.fn(),
        cancel: dictation.cancel,
        retry: vi.fn(),
        dismiss: vi.fn(),
        dismissInserted: vi.fn(),
      },
    };
  },
}));
vi.mock("@/components/ui/voice-glow", () => ({
  useMicrophone: () => ({
    stream: null,
    state: "idle",
    error: null,
    supported: true,
    start: vi.fn(),
    stop: vi.fn(),
  }),
}));

/**
 * The voice call, as a session this test sets (#54). What is under test is what
 * the container does with a call - where the bar goes, what the button starts,
 * how saved turns reach the transcript - not the socket (`use-voice-session.test.tsx`).
 */
const voiceCall = vi.hoisted(() => ({
  call: null as unknown,
  start: vi.fn(),
  end: vi.fn(),
  dismiss: vi.fn(),
  options: {} as { onTurnSaved?: () => void; onConversation?: (id: string) => void },
}));
vi.mock("@/hooks/use-voice-session", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-voice-session")>()),
  useVoiceSession: (options: typeof voiceCall.options) => {
    voiceCall.options = options;
    return {
      call: voiceCall.call,
      localStream: null,
      remoteStream: null,
      start: voiceCall.start,
      end: voiceCall.end,
      setMuted: vi.fn(),
      pressToTalk: vi.fn(),
      decide: vi.fn(),
      dismissUnavailable: vi.fn(),
      dismiss: voiceCall.dismiss,
    };
  },
}));

/** The active organization, with server dictation set up unless told otherwise. */
const organization = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

/** What `GET /agents/{id}/dictation` answers for every agent. */
const readiness = vi.hoisted(() => ({
  current: {
    engine: "server",
    requested: true,
    server_available: true,
    unavailable: null,
    max_seconds: 300,
    provider: "openai",
    format: "wav",
  } as Record<string, unknown>,
}));

const { socket } = vi.hoisted(() => ({
  socket: {
    onMessage: null as ((event: MessageEvent) => void) | null,
    send: vi.fn(),
    isConnected: true,
  },
}));
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (options: { onMessage?: (event: MessageEvent) => void }) => {
    socket.onMessage = options.onMessage ?? null;
    return {
      isConnected: socket.isConnected,
      connect: vi.fn(),
      disconnect: vi.fn(),
      sendMessage: socket.send,
    };
  },
}));

/** Replay one server frame onto the mounted chat, the way the socket would. */
function receive(type: string, data: Record<string, unknown>): void {
  act(() =>
    socket.onMessage?.(new MessageEvent("message", { data: JSON.stringify({ type, data }) })),
  );
}

function mount(
  requestedConversationId?: string,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  requestedMessageId?: string,
  onOpenMessage?: (target: ConversationMessageSearchTarget) => void,
) {
  return render(
    <QueryClientProvider client={client}>
      <ChatContainer
        requestedConversationId={requestedConversationId}
        requestedMessageId={requestedMessageId}
        onOpenMessage={onOpenMessage}
      />
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

/** An already-successful history fixture; pending reads use the real API boundary below. */
function loadTranscript(
  messages: ConversationMessage[],
  cost: ConversationCost | null = null,
  hasEarlier = false,
) {
  const conversation = useConversationStore.getState();
  if (conversation.currentConversationId === null) throw new Error("Select the fixture's chat");
  conversation.setCurrentMessages(messages, cost, hasEarlier, {
    conversationId: conversation.currentConversationId,
    selectionVersion: conversation.selectionVersion,
    accountId: useAuthStore.getState().user?.id ?? null,
    tenantId: useOrgStore.getState().activeOrgId,
  });
}

// How long a wait in this file gives the container to settle. The whole container
// mounts here - queries, stores, the socket - and on the CI runner, which runs every
// suite with coverage at once, a step that takes 76 ms locally has taken over a
// second: three different tests here failed only there, each inside the 1 s default.
// It lengthens only the wait before a real failure is reported; nothing asserted
// changes. Set once for the file, which vitest runs in modules of its own.
const SETTLE = { timeout: 5000 };
beforeAll(() => configure({ asyncUtilTimeout: SETTLE.timeout }));

beforeEach(() => {
  socket.isConnected = true;
  vi.clearAllMocks();
  vi.mocked(apiClient.post).mockReset();
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
      : url === "/conversations/background-tasks"
        ? Promise.resolve([])
        : url === "/me/permissions"
          ? // A real shape, not the list fallback: `usePermissions` reads
            // `data.permissions` off whatever this answers.
            Promise.resolve({
              organization_id: "org-1",
              role: "member",
              is_app_admin: false,
              permissions: [],
            })
          : url === "/orgs" && organization.current !== null
            ? Promise.resolve({ items: [organization.current], total: 1 })
            : /^\/agents\/[^/]+\/dictation$/.test(url)
              ? Promise.resolve(readiness.current)
              : Promise.resolve({ items: [], total: 0 }),
  );
  organization.current = null;
  readiness.current = {
    engine: "server",
    requested: true,
    server_available: true,
    unavailable: null,
    max_seconds: 300,
    provider: "openai",
    format: "wav",
  };
  dictation.phase = "idle";
  dictation.reason = null;
  dictation.upload = null;
  dictation.inserted = false;
  dictation.format = undefined;
  dictation.send = undefined;
  useAuthStore.setState({
    accessToken: "t-1",
    user: SIGNED_IN as never,
    sessionOwnerId: SIGNED_IN.id,
  });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useAgentSelectionStore.setState({ selectedAgentId: null });
  useComposerIntentStore.setState({ intent: null, shared: null });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  // Drafts and the selected workspace pane intentionally survive component unmounts.
  useChatStore.getState().clearRoomDrafts();
  useBrowserPanelStore.getState().close();
  voiceCall.call = initialCall;
});

describe("the chat header's model selection reaches the next request", () => {
  beforeEach(() => {
    useChatControlsStore.setState({ byScope: {} });
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => {
      if (url === "/me/permissions")
        return Promise.resolve({
          permissions: [
            { permission: "agents:view", scope: "all" },
            { permission: "agents:run", scope: "all" },
            { permission: "connections:manage", scope: "all" },
          ],
        });
      if (url.startsWith("/agents") && !url.includes("/dictation") && !url.includes("/voice"))
        return Promise.resolve({
          items: [
            {
              id: "model-agent",
              slug: "model-agent",
              name: "Model agent",
              status: "published",
              can_run: true,
              published_model: {
                profile_id: "agent-default",
                provider: "openai",
                model: "gpt-5",
                label: "Default GPT",
              },
            },
          ],
          total: 1,
        });
      if (url === "/providers/model-profiles")
        return Promise.resolve({
          items: [
            {
              id: "saved-fast",
              provider: "openai",
              model: "gpt-fast",
              label: "Saved fast model",
              secret_id: "team-key",
              params: {},
              fallback_profile_ids: [],
            },
          ],
          total: 1,
        });
      if (url === "/providers/catalog")
        return Promise.resolve({ items: [{ id: "openai", name: "OpenAI" }] });
      return base(url);
    });
    useAgentSelectionStore.setState({ selectedAgentId: "model-agent", selectedWorkflowId: null });
  });

  afterEach(() => act(() => useChatControlsStore.setState({ byScope: {} })));

  it("sends the header's selected profile without editing the agent or discarding the draft", async () => {
    mount();
    const composer = await screen.findByRole("textbox", { name: "Type a message..." });
    await userEvent.type(composer, "Use the selected model");
    await userEvent.click(
      await screen.findByRole("button", { name: "Choose chat model: Default GPT" }),
    );
    await userEvent.click(await screen.findByRole("radio", { name: "Saved fast model" }));
    expect(messageOf(composer)).toBe("Use the selected model");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expect(
        socket.send.mock.calls.map(([frame]) => frame).find((frame) => frame.message),
      ).toMatchObject({
        message: "Use the selected model",
        model_profile_id: "saved-fast",
        agent_id: "model-agent",
      }),
    );
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("omits the override from the next request after restoring the agent's model", async () => {
    useChatControlsStore
      .getState()
      .update(currentChatControlScope(), { modelProfileId: "saved-fast" });
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Choose chat model: Saved fast model" }),
    );
    await userEvent.click(screen.getByRole("button", { name: /Use agent's model/ }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Type a message..." }),
      "Use the agent default",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expect(
        socket.send.mock.calls.map(([frame]) => frame).find((frame) => frame.message),
      ).toBeDefined(),
    );
    const sent = socket.send.mock.calls.map(([frame]) => frame).find((frame) => frame.message);
    expect(sent).not.toHaveProperty("model_profile_id");
    expect(apiClient.patch).not.toHaveBeenCalled();
  });
});

describe("the chat container - project room workspace", () => {
  function savedProjectRoom(canPost: boolean): void {
    const conversation = {
      id: "c-room",
      title: "Launch room",
      user_id: SIGNED_IN.id,
      project_id: "p-room",
    };
    const project: Project = {
      id: "p-room",
      name: "Launch",
      description: null,
      instructions: "",
      default_agent_id: null,
      default_agent_name: null,
      owner_user_id: SIGNED_IN.id,
      visibility: "private",
      backend: "state",
      runtime: null,
      chat_count: 1,
      last_active_at: null,
      shared_groups: [],
      can_use: canPost,
      can_edit: canPost,
      created_at: null,
      updated_at: null,
    };
    const workspace: ConversationWorkspace = {
      scope: "project",
      backend: "state",
      owner_label: "Launch",
      total: 1,
      bytes_total: 12,
      bytes_limit: null,
      truncated: false,
      unreadable_reason: null,
      items: [
        {
          path: "/report.md",
          size: 12,
          is_dir: false,
          modified_at: null,
          preview: null,
          thumbnail: null,
        },
      ],
    };
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => {
      if (url.startsWith("/conversations?"))
        return Promise.resolve({ items: [conversation], total: 1 });
      if (url === "/projects/p-room") return Promise.resolve(project);
      if (url === "/conversations/c-room/metadata") return Promise.resolve(conversation);
      if (url === "/conversations/c-room/room-requests")
        return Promise.resolve({ items: [], total: 0, can_post: canPost });
      if (url === "/conversations/c-room/workspace") return Promise.resolve(workspace);
      return base(url);
    });
    useConversationStore.getState().setCurrentConversationId(conversation.id);
  }

  function roomAgent(id: string, name: string): RoomParticipantRead {
    return {
      kind: "agent",
      id,
      name,
      avatar_url: null,
      is_member: true,
      can_add: false,
      can_mention: true,
      auto_reply: false,
    };
  }

  function mountProjectRoomWithOpenThread(
    mentionables: RoomParticipantRead[] = [roomAgent("agent-a", "Writer")],
  ): void {
    savedProjectRoom(true);
    const root = {
      id: "root-a",
      conversation_id: "c-room",
      role: "user" as const,
      content: "Original room topic",
      created_at: "2026-11-14T00:00:00Z",
    };
    loadTranscript([root]);
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/conversations/c-room/room-mentionables"
        ? Promise.resolve({
            items: mentionables,
          })
        : url.startsWith("/conversations/c-room/room-threads/root-a?")
          ? Promise.resolve({ root, items: [], total: 0, can_post: true })
          : fallback(url),
    );
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ChatContainer
          requestedConversationId="c-room"
          requestedThreadRootId="root-a"
          onCloseThread={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  it("holds an unsent direct draft until the first project room has an id", async () => {
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/projects/p-room"
        ? Promise.resolve({ id: "p-room", name: "Launch", can_use: true })
        : url === "/conversations/c-room/room-requests"
          ? Promise.resolve({ items: [], total: 0, can_post: true })
          : url === "/conversations/c-room/room-mentionables"
            ? Promise.resolve({ items: [] })
            : base(url),
    );
    const initialContentRef = { current: "An unsent direct question" };
    const consumeInitialContent = vi.fn(() => {
      const content = initialContentRef.current;
      initialContentRef.current = "";
      return content;
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const roomComposer = (conversationId: string | null) => (
      <TeamRoomComposer
        key={conversationId ?? "new-room"}
        conversationId={conversationId}
        projectId="p-room"
        readOnly={false}
        onTyping={vi.fn()}
        consumeInitialContent={consumeInitialContent}
      />
    );
    const view = render(
      <QueryClientProvider client={client}>{roomComposer(null)}</QueryClientProvider>,
    );

    expect(initialContentRef.current).toBe("An unsent direct question");
    expect(consumeInitialContent).not.toHaveBeenCalled();

    view.rerender(
      <QueryClientProvider client={client}>{roomComposer("c-room")}</QueryClientProvider>,
    );
    const composer = await screen.findByRole("textbox", { name: "Message to the team" }, SETTLE);
    expect(composer).toHaveValue("An unsent direct question");
    expect(initialContentRef.current).toBe("");
    expect(consumeInitialContent).toHaveBeenCalledTimes(1);
  });

  it("keeps the draft when the same conversation becomes a project room", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const base = get.getMockImplementation()!;
    const conversation = {
      id: "c-room",
      title: "Launch room",
      user_id: SIGNED_IN.id,
    };
    const project: Project = {
      id: "p-room",
      name: "Launch",
      description: null,
      instructions: "",
      default_agent_id: null,
      default_agent_name: null,
      owner_user_id: SIGNED_IN.id,
      visibility: "private",
      backend: "state",
      runtime: null,
      chat_count: 1,
      last_active_at: null,
      shared_groups: [],
      can_use: true,
      can_edit: true,
      created_at: null,
      updated_at: null,
    };
    let isRoom = false;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({
            items: [isRoom ? { ...conversation, project_id: "p-room" } : conversation],
            total: 1,
          })
        : url === "/projects/p-room"
          ? Promise.resolve(project)
          : url === "/conversations/c-room/room-requests"
            ? Promise.resolve({ items: [], total: 0, can_post: true })
            : url === "/conversations/c-room/room-mentionables"
              ? Promise.resolve({ items: [] })
              : base(url),
    );
    useConversationStore.getState().setCurrentConversationId("c-room");
    mount(undefined, client);
    const directComposer = await screen.findByRole(
      "textbox",
      { name: "Type a message..." },
      SETTLE,
    );
    await userEvent.type(directComposer, "Keep this draft in its converted room");

    isRoom = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.conversations.all() });
    });
    const roomComposer = await screen.findByRole(
      "textbox",
      { name: "Message to the team" },
      SETTLE,
    );
    expect(roomComposer).toHaveValue("Keep this draft in its converted room");
  });

  it("hands a new-chat draft to the exact project room created from that selection", async () => {
    const base = get.getMockImplementation()!;
    const conversation = {
      id: "c-room",
      title: "Launch room",
      user_id: SIGNED_IN.id,
      project_id: "p-room",
    };
    const project: Project = {
      id: "p-room",
      name: "Launch",
      description: null,
      instructions: "",
      default_agent_id: null,
      default_agent_name: null,
      owner_user_id: SIGNED_IN.id,
      visibility: "private",
      backend: "state",
      runtime: null,
      chat_count: 1,
      last_active_at: null,
      shared_groups: [],
      can_use: true,
      can_edit: true,
      created_at: null,
      updated_at: null,
    };
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({ items: [conversation], total: 1 })
        : url === "/projects/p-room"
          ? Promise.resolve(project)
          : url === "/conversations/c-room/room-requests"
            ? Promise.resolve({ items: [], total: 0, can_post: true })
            : url === "/conversations/c-room/room-mentionables"
              ? Promise.resolve({ items: [] })
              : base(url),
    );
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "c-room",
      project_id: "p-room",
    } as never);
    mount();
    const directComposer = await screen.findByRole(
      "textbox",
      { name: "Type a message..." },
      SETTLE,
    );
    await userEvent.type(directComposer, "Keep this question in the new room");

    act(() => useConversationStore.getState().setPendingProjectId("p-room"));
    await userEvent.click(await screen.findByRole("button", { name: "New team room" }, SETTLE));
    await waitFor(
      () =>
        expect(apiClient.post).toHaveBeenCalledWith("/conversations", {
          project_id: "p-room",
          title: expect.any(String),
        }),
      SETTLE,
    );
    await waitFor(
      () => expect(routerPush).toHaveBeenCalledExactlyOnceWith("/chat?id=c-room"),
      SETTLE,
    );

    act(() => useConversationStore.getState().setCurrentConversationId("c-room"));
    const roomComposer = await screen.findByRole(
      "textbox",
      { name: "Message to the team" },
      SETTLE,
    );
    expect(roomComposer).toHaveValue("Keep this question in the new room");
  });

  it("refuses a room-create handoff after the selection generation changes", async () => {
    const base = get.getMockImplementation()!;
    const room = {
      id: "c-room",
      title: "Launch room",
      user_id: SIGNED_IN.id,
      project_id: "p-room",
    };
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({ items: [room], total: 1 })
        : url === "/projects/p-room"
          ? Promise.resolve({ id: "p-room", name: "Launch", can_use: true })
          : url === "/conversations/c-room/room-requests"
            ? Promise.resolve({ items: [], total: 0, can_post: true })
            : url === "/conversations/c-room/room-mentionables"
              ? Promise.resolve({ items: [] })
              : base(url),
    );
    let finishCreation!: (value: { id: string; project_id: string }) => void;
    const creation = new Promise<{ id: string; project_id: string }>((resolve) => {
      finishCreation = resolve;
    });
    vi.mocked(apiClient.post).mockReturnValueOnce(creation as never);
    mount();
    const directComposer = await screen.findByRole(
      "textbox",
      { name: "Type a message..." },
      SETTLE,
    );
    await userEvent.type(directComposer, "Draft from the selection that left");
    act(() => useConversationStore.getState().setPendingProjectId("p-room"));
    await userEvent.click(await screen.findByRole("button", { name: "New team room" }, SETTLE));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1), SETTLE);

    // The empty chat stays mounted, but this visit to it has been superseded.
    act(() => useConversationStore.getState().setCurrentConversationId(null));
    await act(async () => finishCreation({ id: "c-room", project_id: "p-room" }));
    expect(routerPush).not.toHaveBeenCalled();

    // Even if the created room is opened later, the old generation cannot seed it.
    act(() => useConversationStore.getState().setCurrentConversationId("c-room"));
    const roomComposer = await screen.findByRole(
      "textbox",
      { name: "Message to the team" },
      SETTLE,
    );
    expect(roomComposer).toHaveValue("");
  });

  it("does not transfer a private conversation draft into a different project room", async () => {
    const base = get.getMockImplementation()!;
    const directConversation = {
      id: "c-private",
      title: "Private chat",
      user_id: SIGNED_IN.id,
    };
    const roomConversation = {
      id: "c-room-b",
      title: "Launch room",
      user_id: SIGNED_IN.id,
      project_id: "p-room",
    };
    const project: Project = {
      id: "p-room",
      name: "Launch",
      description: null,
      instructions: "",
      default_agent_id: null,
      default_agent_name: null,
      owner_user_id: SIGNED_IN.id,
      visibility: "private",
      backend: "state",
      runtime: null,
      chat_count: 1,
      last_active_at: null,
      shared_groups: [],
      can_use: true,
      can_edit: true,
      created_at: null,
      updated_at: null,
    };
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({ items: [directConversation, roomConversation], total: 2 })
        : url === "/projects/p-room"
          ? Promise.resolve(project)
          : url === "/conversations/c-room-b/room-requests"
            ? Promise.resolve({ items: [], total: 0, can_post: true })
            : url === "/conversations/c-room-b/room-mentionables"
              ? Promise.resolve({ items: [] })
              : base(url),
    );
    useConversationStore.getState().setCurrentConversationId("c-private");
    mount();
    const directComposer = await screen.findByRole(
      "textbox",
      { name: "Type a message..." },
      SETTLE,
    );
    await userEvent.type(directComposer, "Private draft for A");

    act(() => useConversationStore.getState().setCurrentConversationId("c-room-b"));
    const roomComposer = await screen.findByRole(
      "textbox",
      { name: "Message to the team" },
      SETTLE,
    );
    expect(roomComposer).toHaveValue("");
  });

  it.each(["account", "organization"] as const)(
    "resets a new-chat draft when its %s owner changes",
    async (boundary) => {
      mount();
      const before = await screen.findByRole("textbox", { name: "Type a message..." }, SETTLE);
      await userEvent.type(before, "Only the original identity can see this");

      act(() => {
        if (boundary === "account") {
          useAuthStore.setState({
            user: { ...SIGNED_IN, id: "u-2", email: "other@example.test" } as never,
            sessionOwnerId: "u-2",
          });
        } else {
          useOrgStore.getState().setActiveOrgId("org-2");
        }
      });

      const after = await screen.findByRole("textbox", { name: "Type a message..." }, SETTLE);
      expect(after).not.toBe(before);
      expect(messageOf(after)).toBe("");
    },
  );

  it("keeps tagged replies out of the main view while room metadata and thread authorization are pending", async () => {
    savedProjectRoom(true);
    const root = {
      id: "root-a",
      conversation_id: "c-room",
      role: "user" as const,
      content: "Original room topic",
      created_at: "2026-11-14T00:00:00Z",
      thread_reply_count: 1,
    };
    const reply = {
      id: "reply-a",
      conversation_id: "c-room",
      role: "user" as const,
      content: "Scoped reply A",
      created_at: "2026-11-14T00:00:01Z",
      thread_root_message_id: "root-a",
    };
    loadTranscript([root, reply]);
    const base = get.getMockImplementation()!;
    let authorize!: (value: unknown) => void;
    let metadata!: (value: unknown) => void;
    let listing!: (value: unknown) => void;
    get.mockImplementation((url: string) => {
      if (url.startsWith("/conversations?"))
        return new Promise((resolve) => {
          listing = resolve;
        });
      if (url === "/conversations/c-room/metadata")
        return new Promise((resolve) => {
          metadata = resolve;
        });
      if (url.includes("/room-threads/root-a?"))
        return new Promise((resolve) => {
          authorize = resolve;
        });
      return base(url);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const openThread = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <ChatContainer
          requestedConversationId="c-room"
          requestedThreadRootId="root-a"
          onCloseThread={vi.fn()}
          onOpenThread={openThread}
        />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(authorize).toBeDefined(), SETTLE);
    expect(screen.queryByText("Scoped reply A")).toBeNull();
    expect(screen.getByText("Original room topic")).toBeInTheDocument();
    await act(async () => authorize({ root, items: [reply], total: 1, can_post: true }));
    const panel = screen.getByRole("complementary", { name: "Thread" });
    expect(await within(panel).findByText("Scoped reply A")).toBeInTheDocument();
    expect(screen.getAllByText("Scoped reply A")).toHaveLength(1);
    expect(within(panel).queryByRole("textbox", { name: "Reply to thread" })).toBeNull();
    await act(async () => {
      const conversation = {
        id: "c-room",
        user_id: SIGNED_IN.id,
        project_id: "p-room",
        title: "Launch room",
      };
      listing({ items: [conversation], total: 1 });
      metadata?.(conversation);
    });
    await within(panel).findByRole("textbox", { name: "Reply to thread" });
    receive("turn_attached", { conversation_id: "c-room", thread_root_message_id: "root-b" });
    receive("model_request_start", { conversation_id: "c-room", thread_root_message_id: "root-b" });
    receive("text_delta", {
      conversation_id: "c-room",
      thread_root_message_id: "root-b",
      index: 0,
      content: "Live in another thread",
    });
    expect(screen.queryByText("Live in another thread")).toBeNull();
    receive("ask_user", {
      conversation_id: "c-room",
      thread_root_message_id: "root-b",
      questions: [{ question: "Question in another thread", options: [{ label: "Continue" }] }],
    });
    expect(within(panel).queryByText("Question in another thread")).toBeNull();
    const jump = within(panel).getByRole("button", { name: "Open thread" });
    expect(screen.getAllByRole("button", { name: "Open thread" })).toHaveLength(1);
    await userEvent.click(jump);
    expect(openThread).toHaveBeenCalledWith("root-b");
  });

  it("keeps the main and thread mention listboxes and active options uniquely addressable", async () => {
    mountProjectRoomWithOpenThread();
    const mainComposer = await screen.findByRole(
      "textbox",
      { name: "Message to the team" },
      SETTLE,
    );
    const panel = await screen.findByRole("complementary", { name: "Thread" }, SETTLE);
    const threadComposer = await within(panel).findByRole(
      "textbox",
      { name: "Reply to thread" },
      SETTLE,
    );

    await userEvent.type(mainComposer, "@Wri");
    await userEvent.type(threadComposer, "@Wri");

    const options = await screen.findAllByRole("option", undefined, SETTLE);
    expect(options).toHaveLength(2);
    const listboxIds = [
      mainComposer.getAttribute("aria-controls"),
      threadComposer.getAttribute("aria-controls"),
    ];
    const controls = listboxIds.filter((id): id is string => id !== null);
    expect(controls).toHaveLength(2);
    expect(new Set(controls).size).toBe(2);
    const listboxes = screen.getAllByRole("listbox");
    expect(listboxes).toHaveLength(2);
    expect(new Set(listboxes.map((listbox) => listbox.id))).toEqual(new Set(controls));

    const activeOptionIds = [
      mainComposer.getAttribute("aria-activedescendant"),
      threadComposer.getAttribute("aria-activedescendant"),
    ];
    const activeOptions = activeOptionIds.filter((id): id is string => id !== null);
    expect(activeOptions).toHaveLength(2);
    expect(new Set(activeOptions).size).toBe(2);
    expect(activeOptions.every((id) => options.some((option) => option.id === id))).toBe(true);
  });

  it("resets keyboard mention selection when a query cycles through a different match set", async () => {
    mountProjectRoomWithOpenThread([
      roomAgent("agent-writer", "Writer"),
      roomAgent("agent-willow", "Willow"),
      roomAgent("agent-warden", "Warden"),
    ]);
    const composer = await screen.findByRole("textbox", { name: "Message to the team" }, SETTLE);
    await userEvent.type(composer, "@W");
    const listbox = await screen.findByRole("listbox", undefined, SETTLE);
    expect(composer).toHaveAttribute("aria-activedescendant", `${listbox.id}-0`);

    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(composer).toHaveAttribute("aria-activedescendant", `${listbox.id}-2`);

    await userEvent.clear(composer);
    await userEvent.type(composer, "@Wi");
    expect(composer).toHaveAttribute("aria-activedescendant", `${listbox.id}-0`);

    await userEvent.clear(composer);
    await userEvent.type(composer, "@W");
    expect(composer).toHaveAttribute("aria-activedescendant", `${listbox.id}-0`);
  });

  it("closes the mention palette after an accepted post and keeps unpicked text literal", async () => {
    mountProjectRoomWithOpenThread();
    const submitRoomPost = vi
      .fn<(input: unknown) => Promise<unknown>>()
      .mockRejectedValueOnce(new TypeError("Network lost"))
      .mockResolvedValueOnce({
        message: {
          id: "saved-room-message",
          conversation_id: "c-room",
          role: "user",
          content: "@Wri",
          created_at: "2026-11-14T00:00:00Z",
        },
        request: null,
      } as never);
    vi.mocked(apiClient.post).mockImplementation(async (path, input) =>
      path === "/conversations/c-room/room-messages" ? submitRoomPost(input) : {},
    );
    const composer = await screen.findByRole("textbox", { name: "Message to the team" }, SETTLE);
    await userEvent.type(composer, "@Wri");
    expect(await screen.findByRole("listbox", undefined, SETTLE)).toBeVisible();

    const form = composer.closest("form")!;
    fireEvent.submit(form);
    await waitFor(
      () => expect(within(form).getByRole("button", { name: /retry/i })).toBeEnabled(),
      SETTLE,
    );
    expect(composer).toHaveValue("@Wri");
    expect(screen.getByRole("listbox")).toBeVisible();
    const frozen = submitRoomPost.mock.calls[0]![0];

    fireEvent.submit(form);

    await waitFor(() => expect(submitRoomPost).toHaveBeenCalledTimes(2), SETTLE);
    expect(submitRoomPost.mock.calls[1]![0]).toEqual(frozen);
    await waitFor(() => expect(composer).toHaveValue(""), SETTLE);
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull(), SETTLE);
    expect(submitRoomPost).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ content: "@Wri", mentions: [] }),
    );
  });

  it("opens retained thread history read-only after its project is detached", async () => {
    savedProjectRoom(true);
    const root = {
      id: "root-history",
      conversation_id: "c-room",
      role: "user" as const,
      content: "Retained original",
      created_at: "2026-11-14T00:00:00Z",
      thread_reply_count: 1,
    };
    const reply = {
      id: "history-reply",
      conversation_id: "c-room",
      role: "user" as const,
      content: "Retained thread reply",
      created_at: "2026-11-14T00:00:01Z",
      thread_root_message_id: "root-history",
    };
    loadTranscript([root]);
    const base = get.getMockImplementation()!;
    const conversation = {
      id: "c-room",
      user_id: SIGNED_IN.id,
      project_id: null,
      title: "Retained conversation",
    };
    get.mockImplementation((url: string) => {
      if (url.startsWith("/conversations?"))
        return Promise.resolve({ items: [conversation], total: 1 });
      if (url === "/conversations/c-room/metadata") return Promise.resolve(conversation);
      if (url.includes("/room-threads/root-history?"))
        return Promise.resolve({ root, items: [reply], total: 1, can_post: false });
      return base(url);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const open = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <ChatContainer
          requestedConversationId="c-room"
          requestedThreadRootId="root-history"
          onCloseThread={vi.fn()}
          onOpenThread={open}
        />
      </QueryClientProvider>,
    );
    const panel = await screen.findByRole("complementary", { name: "Thread" });
    expect(await within(panel).findByText("Retained thread reply")).toBeInTheDocument();
    expect(within(panel).queryByRole("textbox", { name: "Reply to thread" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "1 reply" }));
    expect(open).toHaveBeenCalledWith("root-history");
  });
  it("keeps project-room files reachable without losing the room draft", async () => {
    savedProjectRoom(true);
    mount();
    const composer = await screen.findByRole("textbox", { name: "Message to the team" });
    await userEvent.type(composer, "An unsent room draft");
    const files = await screen.findByRole("button", { name: /^Show the files/ });
    await userEvent.click(files);
    await waitFor(() => expect(screen.getByText("report.md")).toBeVisible());
    expect(composer).toHaveValue("An unsent room draft");

    await userEvent.click(screen.getByRole("button", { name: "Close the file panel" }));
    await waitFor(() => expect(screen.queryByText("report.md")).toBeNull());
    expect(files).toHaveFocus();
    expect(composer).toHaveValue("An unsent room draft");
    expect(composer).toBeEnabled();
  });

  it("keeps personal-agent settings out of team rooms", async () => {
    savedProjectRoom(true);
    useAgentSelectionStore.setState({ selectedAgentId: "personal-agent" });
    mount();
    const composer = await screen.findByRole("textbox", { name: "Message to the team" });
    await userEvent.type(composer, "Keep this room draft");

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("personal-agent");
    expect(screen.getByRole("button", { name: "Open Browser" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open Computer" })).toBeVisible();
    expect(await screen.findByRole("button", { name: /^Show the files/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open agent settings" })).toBeNull();

    act(() => useBrowserPanelStore.getState().openSurface("settings"));
    expect(useBrowserPanelStore.getState().surface).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Agent settings" })).toBeNull();
    expect(composer).toHaveValue("Keep this room draft");
  });

  it.each([true, false])(
    "keeps room workspace panes available and directs requests through the room composer (can post: %s)",
    async (canPost) => {
      savedProjectRoom(canPost);
      mount();
      const composer = canPost
        ? await screen.findByRole("textbox", { name: "Message to the team" })
        : null;
      if (composer) await userEvent.type(composer, "An unsent room draft");
      else
        await screen.findByText(
          "You can read this room. Posting requires permission to use its project.",
        );
      const postsBefore = vi.mocked(apiClient.post).mock.calls.length;
      const promptsBefore = socket.send.mock.calls.filter(([frame]) => frame.message).length;

      for (const [opener, action] of [
        ["Open Browser", "Ask agent to open browser"],
        ["Open Computer", "Ask agent to start computer"],
      ]) {
        await userEvent.click(screen.getByRole("button", { name: opener }));
        const guidance = canPost
          ? "Mention the agent you want in the room composer and ask them to open the browser or computer."
          : "You can view this conversation, but cannot start a session here.";
        expect(screen.getByText(guidance)).toBeVisible();
        if (canPost) {
          const start = screen.getByRole("button", { name: action });
          expect(start).toBeDisabled();
          fireEvent.submit(start.closest("form")!);
        } else expect(screen.queryByRole("button", { name: action })).toBeNull();
        if (composer) {
          expect(composer).toHaveValue("An unsent room draft");
          expect(composer).toBeEnabled();
        }
      }
      expect(apiClient.post).toHaveBeenCalledTimes(postsBefore);
      expect(socket.send.mock.calls.filter(([frame]) => frame.message)).toHaveLength(promptsBefore);
      expect(
        screen.queryByText(
          canPost
            ? "You can view this conversation, but cannot start a session here."
            : "Mention the agent you want in the room composer and ask them to open the browser or computer.",
        ),
      ).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "Close workspace panel" }));
    },
  );

  it("keeps project-room files reachable for a reader who cannot post", async () => {
    savedProjectRoom(false);
    mount();
    await screen.findByText(
      "You can read this room. Posting requires permission to use its project.",
    );
    expect(screen.queryByRole("textbox", { name: "Message to the team" })).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: /^Show the files/ }));
    await waitFor(() => expect(screen.getByText("report.md")).toBeVisible());
    await userEvent.click(screen.getByRole("button", { name: "Close the file panel" }));
    await waitFor(() => expect(screen.queryByText("report.md")).toBeNull());
  });

  it("joins an empty room only after its successful history load and displays colleague presence", async () => {
    savedProjectRoom(true);
    useConversationStore.getState().setCurrentConversationId(null);
    let finish!: (value: unknown) => void;
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations/c-room/messages")
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : base(url),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConversations(), { wrapper: Wrapper });
    mount("c-room", client);
    let reading!: Promise<void>;
    act(() => {
      reading = result.current.selectConversation("c-room");
    });
    await waitFor(() => expect(finish).toBeDefined());
    expect(useConversationStore.getState().currentConversationId).toBe("c-room");
    expect(useConversationStore.getState().isLoading).toBe(true);
    expect(useChatStore.getState().loadedTranscript).toBeNull();
    expect(socket.send).not.toHaveBeenCalledWith({ type: "attach", conversation_id: "c-room" });

    await act(async () => {
      finish({ items: [], total: 0, cost: null });
      await reading;
    });
    await waitFor(() =>
      expect(socket.send).toHaveBeenCalledWith({ type: "attach", conversation_id: "c-room" }),
    );
    expect(useChatStore.getState().messages).toEqual([]);
    receive("presence", {
      conversation_id: "c-room",
      people: [{ user_id: "colleague", name: "Colleague", has_avatar: false, avatar_color: null }],
    });
    await waitFor(() => expect(screen.getByText("Colleague is here")).toBeVisible());
  });

  it("keeps the next room turn when a previously empty history refresh finishes late", async () => {
    savedProjectRoom(true);
    loadTranscript([]);
    mount();
    await waitFor(() =>
      expect(socket.send).toHaveBeenCalledWith({ type: "attach", conversation_id: "c-room" }),
    );
    let finish!: (value: unknown) => void;
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations/c-room/messages")
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : base(url),
    );
    receive("turn_attached", { conversation_id: "c-room" });
    receive("turn_followed_to_end", { conversation_id: "c-room" });
    await waitFor(() => expect(finish).toBeDefined());
    receive("turn_attached", { conversation_id: "c-room" });
    receive("turn_prompt", {
      conversation_id: "c-room",
      message_id: "next-question",
      content: "Next question",
      sender: { user_id: "colleague", name: "Colleague" },
    });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "New answer" });
    await act(async () => finish({ items: [], total: 0, cost: null }));
    receive("text_delta", { index: 0, content: " continues" });
    expect(useChatStore.getState().messages.map((message) => message.content)).toEqual([
      "Next question",
      "New answer continues",
    ]);
    receive("final_result", { output: "New answer continues" });
    receive("complete", {});
    await waitFor(() => expect(screen.getByText("New answer continues")).toBeVisible());
  });
});

describe("the chat container - answering a durable question", () => {
  it("keeps the question disabled offline and resumes on the connected socket", async () => {
    mount();
    await screen.findByRole("button", { name: "Voice input" });
    receive("model_request_start", {});
    receive("tool_call", { tool_name: "ask_user_question", tool_call_id: "ask-1", args: {} });
    receive("user_question_required", {
      run_id: "r-1",
      questions: [
        {
          tool_call_id: "ask-1",
          questions: [
            { question: "How formal?", options: [{ label: "Casual" }], allow_custom: true },
          ],
        },
      ],
    });
    receive("complete", {});
    act(() => {
      socket.isConnected = false;
      useChatStore.setState({ messages: [...useChatStore.getState().messages] });
    });
    const answer = screen.getByRole("button", { name: /Casual/ });
    expect(answer).toBeDisabled();
    act(() => {
      socket.isConnected = true;
      useChatStore.setState({ messages: [...useChatStore.getState().messages] });
    });
    await userEvent.click(screen.getByRole("button", { name: /Casual/ }));
    const submitted = socket.send.mock.calls
      .map(([frame]) => frame)
      .find((frame) => frame.type === "answer_run");
    expect(submitted).toMatchObject({
      run_id: "r-1",
      responses: { "ask-1": [{ answer: "", selected: ["Casual"], skipped: false }] },
    });
    await act(async () =>
      receive("run_answer_result", {
        request_id: submitted.request_id,
        result: {
          run_id: "r-1",
          status: "completed",
          output: "Your answer was received.",
          cost_usd: "0",
          input_tokens: 1,
          output_tokens: 1,
          cost_is_partial: false,
        },
      }),
    );
    expect(screen.queryByText("How formal?")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Your answer was received.")).toBeInTheDocument());
  });
});

describe("the chat container - Stop without a restored decision card", () => {
  it.each(["awaiting_answer", "awaiting_approval"] as const)(
    "offers Stop after restoring %s fails",
    async (status) => {
      const fallback = get.getMockImplementation()!;
      get.mockImplementation((url: string) => {
        if (url === "/me/permissions")
          return Promise.resolve({
            organization_id: "org-1",
            role: "admin",
            is_app_admin: false,
            permissions: [{ permission: "approvals:decide", scope: "all" }],
          });
        if (url.endsWith("/can-stop")) return Promise.resolve(true);
        if (url.endsWith("/questions") || url.endsWith("/parked"))
          return Promise.reject(new Error("offline"));
        return fallback(url);
      });
      vi.mocked(apiClient.post).mockResolvedValue("Not performed: the run was stopped.");
      mount();
      await screen.findByRole("button", { name: "Voice input" });
      act(() =>
        useChatStore.getState().addMessage({
          id: "parked-message",
          role: "assistant",
          content: "Waiting",
          timestamp: new Date(),
          runId: "parked-run",
          toolCalls: [{ id: "call", name: "execute", args: {}, status }],
        }),
      );
      const stop = await screen.findByRole("button", { name: "Stop generating" });
      await userEvent.click(stop);
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/runs/parked-run/cancel"));
      await waitFor(() => expect(useChatStore.getState().messages[0]?.wasStopped).toBe(true));
    },
  );
});

describe("the chat container - hosted workspace with a restored decision", () => {
  it.each(["awaiting_answer", "awaiting_approval"] as const)(
    "refuses a hosted start while %s is restored without an active turn",
    async (status) => {
      const fallback = get.getMockImplementation()!;
      get.mockImplementation((url: string) => {
        if (url === "/agents")
          return Promise.resolve({
            items: [
              {
                id: "hosted-agent",
                slug: "hosted-agent",
                name: "Hosted agent",
                status: "published",
                can_run: true,
                published_capabilities: ["browser_use", "computer_use"],
                published_hosted_capabilities: ["browser_use", "computer_use"],
                local_workspace: false,
                local_coding_agent: null,
              },
            ],
            total: 1,
          });
        if (url === "/me/permissions")
          return Promise.resolve({
            organization_id: "org-1",
            role: "admin",
            is_app_admin: false,
            permissions: [{ permission: "approvals:decide", scope: "all" }],
          });
        if (url.endsWith("/can-stop")) return Promise.resolve(true);
        if (url === "/runs/parked-run/parked")
          return Promise.resolve([
            { id: "approval", tool_call_id: "call", tool_name: "execute", tool_args: {} },
          ]);
        if (url === "/runs/parked-run/questions")
          return Promise.resolve([
            {
              tool_call_id: "call",
              questions: [
                { question: "How formal?", options: [{ label: "Casual" }], allow_custom: true },
              ],
            },
          ]);
        return fallback(url);
      });
      useAgentSelectionStore.setState({ selectedAgentId: "hosted-agent" });
      mount();
      await userEvent.click(await screen.findByRole("button", { name: "Open Computer" }));
      const start = screen.getByRole("button", { name: "Ask agent to start computer" });
      await waitFor(() => expect(start).toBeEnabled());

      act(() =>
        useChatStore.getState().addMessage({
          id: "parked-message",
          role: "assistant",
          content: "Waiting",
          timestamp: new Date(),
          runId: "parked-run",
          toolCalls: [{ id: "call", name: "execute", args: {}, status }],
        }),
      );
      await screen.findByRole("button", {
        name: status === "awaiting_approval" ? "Approve" : /Casual/,
      });
      await waitFor(() => expect(start).toBeDisabled());
      const promptsBefore = socket.send.mock.calls.filter(([frame]) => frame.message).length;
      fireEvent.submit(start.closest("form")!);
      expect(socket.send.mock.calls.filter(([frame]) => frame.message)).toHaveLength(promptsBefore);
      await userEvent.click(screen.getByRole("button", { name: "Close workspace panel" }));
    },
  );
});

/**
 * Every ResizeObserver the chat makes, so a test can say an element changed
 * size. The dock's height is padding under the transcript, not content, so
 * the transcript's own observer never hears of it.
 */
function observeSizes() {
  const observers: { grew: () => void; targets: Element[] }[] = [];
  class FakeResize {
    private readonly seen: { grew: () => void; targets: Element[] };
    constructor(callback: () => void) {
      this.seen = { grew: callback, targets: [] };
      observers.push(this.seen);
    }
    observe(element: Element) {
      this.seen.targets.push(element);
    }
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", FakeResize);
  return observers;
}

describe("the chat container - following the transcript", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("follows actual size changes without measuring the transcript on every text delta", async () => {
    const observers = observeSizes();
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    const { dock, scroller } = await scrollerAndDock();
    const readHeight = vi.fn(() => 2000);
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, get: readHeight });
    scrollTo.mockClear();
    scrollIntoView.mockClear();
    act(() =>
      useChatStore
        .getState()
        .updateMessage("m-1", (message) => ({ ...message, content: "Still the same height" })),
    );
    expect(readHeight).not.toHaveBeenCalled();
    expect(scrollTo).not.toHaveBeenCalled();
    const follow = observers.find(
      (observer) => observer.targets.includes(scroller) && !observer.targets.includes(dock),
    )!;
    act(() => follow.grew());
    expect(scroller.scrollTop).toBe(2000);
    expect(readHeight).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).not.toHaveBeenCalled();
    scrollTo.mockRestore();
    scrollIntoView.mockRestore();
  });

  /**
   * The transcript's scroller, a screen long and scrolled to its end, and the
   * dock over it. With a message in it: an empty conversation reads from its top
   * and is not followed at all.
   */
  async function scrollerAndDock() {
    mount();
    await screen.findByRole("button", { name: "Voice input" });
    act(() =>
      useChatStore.getState().addMessage({
        id: "m-1",
        role: "user",
        content: "Send the invoice",
        timestamp: new Date(),
      }),
    );
    const dock = screen.getByRole("textbox").closest("[data-chat-dock]") as HTMLElement;
    const scroller = dock.previousElementSibling as HTMLElement;
    expect(scroller).toHaveClass("overflow-y-auto");
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 2000 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 500 });
    return { dock, scroller };
  }

  function growDock(observers: ReturnType<typeof observeSizes>, dock: HTMLElement): void {
    Object.defineProperty(dock, "offsetHeight", { configurable: true, value: 148 });
    act(() => {
      for (const observer of observers) if (observer.targets.includes(dock)) observer.grew();
    });
  }

  it("keeps a reader at the bottom there when the dock grows, as when a call gives the composer back", async () => {
    const observers = observeSizes();
    const { dock, scroller } = await scrollerAndDock();
    scroller.scrollTop = 1500;

    growDock(observers, dock);

    expect(scroller.style.paddingBottom).toBe("148px");
    expect(scroller.scrollTop).toBe(2000);
  });

  it("leaves a reader who scrolled up where they are when the dock grows", async () => {
    const observers = observeSizes();
    const { dock, scroller } = await scrollerAndDock();
    // From the foot, then up: a scroll up is what lets go.
    scroller.scrollTop = 1500;
    fireEvent.scroll(scroller);
    scroller.scrollTop = 200;
    fireEvent.scroll(scroller);

    growDock(observers, dock);

    expect(scroller.style.paddingBottom).toBe("148px");
    expect(scroller.scrollTop).toBe(200);
  });
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
    expect(
      await screen.findByRole("button", { name: /Quarterly report researcher/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Quarterly report researcher/ }));
    expect(screen.getByText(/\$0\.0042/)).toBeInTheDocument();

    act(() => {
      useConversationStore.getState().setCurrentConversationId("c-b");
    });

    expect(screen.queryByText("Quarterly report researcher")).not.toBeInTheDocument();
    expect(screen.queryByText(/\$0\.0042/)).not.toBeInTheDocument();
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

    expect(
      await screen.findByRole("button", { name: /Quarterly report researcher/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Quarterly report researcher/ }));
    expect(screen.getAllByText("read the three filings and list what changed")).toHaveLength(2);
  });
});

describe("the chat container - server dictation", () => {
  beforeEach(() => {
    organization.current = {
      id: "org-1",
      name: "Acme",
      dictation_max_seconds: 300,
    };
    // The engine is the agent's: its readiness says `server` once it is read.
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
  });

  it("shows the pill above the box while the recording is transcribed", async () => {
    dictation.phase = "transcribing";
    mount();

    // The pill floats once the agent's engine is read; nothing glows under the box.
    expect(await screen.findByText("0:42 of audio")).toBeInTheDocument();
    expect(screen.getByTestId("floating-pill")).toBeInTheDocument();
    expect(screen.queryByTestId("voice-glow")).toBeNull();
  });

  it("counts the upload in the pill", async () => {
    dictation.phase = "transcribing";
    dictation.upload = 42;
    mount();

    expect(await screen.findByText("Uploading 42%")).toBeInTheDocument();
  });

  it("shows no note for the words that landed: they are in the box", async () => {
    // `ChatInput`'s status region tells a screen reader "Inserted 2 words".
    dictation.inserted = true;
    mount();

    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    expect(screen.queryByText("Inserted 2 words")).not.toBeInTheDocument();
  });

  it("puts a failure in the strip on top of the box, which loses its top corners", async () => {
    dictation.phase = "failed";
    dictation.reason = "provider_error";
    mount();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Transcription didn't finish.");
    expect(document.querySelector('[data-tour="chat-composer"]')).toHaveClass("rounded-t-none");
  });

  it("tells the recorder the format the agent's readiness names", async () => {
    // A deployment that accepts compressed audio, and an agent on a provider
    // that takes WebM: the backend says so, not a list of providers kept here.
    organization.current = { ...organization.current, speech_to_text_provider: "openai" };
    readiness.current = { ...readiness.current, provider: "groq", format: "webm" };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    await waitFor(() => expect(dictation.format).toBe("webm"));
    expect(get).toHaveBeenCalledWith("/agents/a-1/dictation");
  });

  it("records PCM WAV and has nowhere to send before an agent is chosen", () => {
    organization.current = null;
    useAgentSelectionStore.setState({ selectedAgentId: null });
    mount();

    expect(dictation.format).toBe("wav");
    expect(dictation.send).toBeNull();
  });

  it("sends a recording to the agent chosen", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();
    const recording = new Blob(["a"], { type: "audio/webm" });

    const onProgress = vi.fn();

    await expect(
      dictation.send!(recording, 2, new AbortController().signal, onProgress),
    ).resolves.toBe("hello");
    expect(upload).toHaveBeenCalledWith("/agents/a-1/dictation", expect.any(FormData), {
      signal: expect.any(AbortSignal),
      onProgress,
    });
  });

  it("offers the microphone once the agent's readiness says yes", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    const mic = await screen.findByRole("button", { name: "Voice input" });
    await waitFor(() => expect(mic).not.toHaveAttribute("aria-disabled"));
  });

  it("takes what another app shared into the message, once", async () => {
    useComposerIntentStore.setState({ shared: { id: 7, files: [], text: "from the browser" } });
    const view = mount();

    await waitFor(() => expect(screen.getByText("from the browser")).toBeInTheDocument());
    expect(useComposerIntentStore.getState().shared).toBeNull();
    view.unmount();
    mount();
    await screen.findByRole("button", { name: "Voice input" });
    expect(screen.queryByText("from the browser")).toBeNull();
  });

  it("starts dictating once when a phone shortcut asked, as soon as the engine is known", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useComposerIntentStore.setState({ intent: "dictate" });
    mount();

    await waitFor(() => expect(dictation.start).toHaveBeenCalledOnce());
    expect(useComposerIntentStore.getState().intent).toBeNull();
  });

  it("dictates in the browser for an agent whose switch is off or has no provider", async () => {
    readiness.current = { ...readiness.current, engine: "browser", requested: false };
    dictation.phase = "transcribing";
    mount();

    expect(await screen.findByRole("button", { name: "Voice input" })).toBeInTheDocument();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/agents/a-1/dictation"));
    expect(screen.queryByText("0:42 of audio")).not.toBeInTheDocument();
  });

  it("says the browser is transcribing for an agent whose Dictation switch is off", async () => {
    readiness.current = { ...readiness.current, engine: "browser", requested: false };
    class FakeRecognition {
      start = vi.fn();
      stop = vi.fn();
    }
    vi.stubGlobal("SpeechRecognition", FakeRecognition);
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/agents/a-1/dictation"));

    fireEvent.click(await screen.findByRole("button", { name: "Voice input" }));

    expect(
      await screen.findByText("Dictation isn't turned on for this agent,", { exact: false }),
    ).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("cancels a recording when the agent leaves the server engine mid-sentence", async () => {
    dictation.phase = "recording";
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Stop and transcribe" });
    dictation.cancel.mockClear();

    readiness.current = { ...readiness.current, engine: "browser" };
    await act(() => client.invalidateQueries());

    // The bar with its Stop button is gone, so the recording goes with it.
    await waitFor(() => expect(dictation.cancel).toHaveBeenCalled());
    // Gone once the pill has finished leaving.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Stop and transcribe" })).not.toBeInTheDocument(),
    );
  });

  it("draws no recording pill for the browser engine", async () => {
    readiness.current = { ...readiness.current, engine: "browser" };
    dictation.phase = "transcribing";
    mount();

    expect(await screen.findByRole("button", { name: "Voice input" })).toBeInTheDocument();
    expect(screen.queryByText("0:42 of audio")).not.toBeInTheDocument();
  });
});

describe("the chat container - a voice call (#54)", () => {
  const READY_VOICE = {
    available: true,
    unavailable: null,
    transport: "webrtc",
    provider: "openai",
    model: "gpt-realtime",
    cap_seconds: 600,
  };
  const LIVE_CALL = {
    ...initialCall,
    phase: "live",
    activity: "listening",
    callId: "c1",
    conversationId: "c-a",
    startedAt: Date.now(),
    capSeconds: 600,
  };

  /** The call button once the agent's readiness has said yes. */
  async function offeredCall(): Promise<HTMLElement> {
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start a voice call" })).not.toHaveAttribute(
        "aria-disabled",
      ),
    );
    return screen.getByRole("button", { name: "Start a voice call" });
  }

  beforeEach(() => {
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      /^\/agents\/[^/]+\/voice$/.test(url) ? Promise.resolve(READY_VOICE) : base(url),
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  it("offers no call before an agent is chosen", async () => {
    mount();
    await screen.findByRole("button", { name: "Voice input" });
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
  });

  it("starts a call with the selected agent, in the conversation that is open", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useConversationStore.getState().setCurrentConversationId("c-a");
    mount();
    fireEvent.click(await offeredCall());
    expect(voiceCall.start).toHaveBeenCalledWith({
      kind: "console",
      agentId: "a-1",
      conversationId: "c-a",
      transport: "webrtc",
    });
  });

  it("starts the call a phone shortcut asked for once the agent can take one", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useComposerIntentStore.setState({ intent: "call" });
    mount();
    await waitFor(() => expect(voiceCall.start).toHaveBeenCalledOnce());
    expect(useComposerIntentStore.getState().intent).toBeNull();
  });

  it("drops a shortcut's call the agent cannot take, leaving the button to say why", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useComposerIntentStore.setState({ intent: "call" });
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      /\/voice$/.test(url)
        ? Promise.resolve({ ...READY_VOICE, available: false, unavailable: "no_key" })
        : base(url),
    );
    mount();
    await waitFor(() => expect(useComposerIntentStore.getState().intent).toBeNull());
    expect(voiceCall.start).not.toHaveBeenCalled();
  });

  it("crosses the button out, with the reason, for an agent whose voice cannot take a call", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      /\/voice$/.test(url)
        ? Promise.resolve({ ...READY_VOICE, available: false, unavailable: "no_key" })
        : base(url),
    );
    mount();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Start a voice call",
          description: /This agent's voice has no key/,
        }),
      ).toHaveAttribute("aria-disabled", "true"),
    );
    // In Send's place all the same: an empty composer has nothing to send.
    expect(screen.queryByRole("button", { name: "Send message" })).toBeNull();
  });

  it("turns the composer into the call bar while the call is on, so nothing is sent beside it", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = LIVE_CALL;
    const { container } = mount();
    expect(await screen.findByRole("group", { name: "Voice call" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End call" })).toBeInTheDocument();
    // The composer is still mounted, so a draft survives the call - and closed.
    expect(container.querySelector('button[type="submit"]')).toBeDisabled();
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-disabled", "true");
  });

  it("keeps an active call's hang-up control reachable when metadata cannot be read", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useConversationStore.getState().setCurrentConversationId("c-not-listed");
    voiceCall.call = LIVE_CALL;
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.endsWith("/metadata")
        ? Promise.reject(new Error("Access could not be checked"))
        : base(url),
    );
    mount();
    const end = await screen.findByRole("button", { name: "End call" });
    await waitFor(() => expect(get).toHaveBeenCalledWith("/conversations/c-not-listed/metadata"));
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(end);
    expect(voiceCall.end).toHaveBeenCalled();
  });

  it("reads the transcript again in place as each spoken turn is saved", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useConversationStore.getState().setCurrentConversationId("c-a");
    mount();
    fireEvent.click(await offeredCall());
    get.mockClear();
    const loading = vi.fn();
    const stop = useConversationStore.subscribe((state) => loading(state.isLoading));
    act(() => voiceCall.options.onTurnSaved?.());
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/conversations/c-a/messages?latest=true&limit=101&top_level_only=true",
      ),
    );
    stop();
    // Not the select path: nothing is cleared and no skeleton is drawn.
    expect(loading).not.toHaveBeenCalledWith(true);
  });

  it("opens the conversation a call started, and keeps reading it", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();
    fireEvent.click(await offeredCall());
    act(() => voiceCall.options.onConversation?.("c-new"));
    expect(useConversationStore.getState().currentConversationId).toBe("c-new");
    get.mockClear();
    act(() => voiceCall.options.onTurnSaved?.());
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/conversations/c-new/messages?latest=true&limit=101&top_level_only=true",
      ),
    );
    expect(voiceCall.end).not.toHaveBeenCalled();
  });

  it("hangs a call up when another conversation is opened", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useConversationStore.getState().setCurrentConversationId("c-a");
    mount();
    fireEvent.click(await offeredCall());
    act(() => useConversationStore.getState().setCurrentConversationId("c-b"));
    expect(voiceCall.end).toHaveBeenCalled();
    expect(voiceCall.dismiss).toHaveBeenCalled();
    // A saved turn from the old call no longer reloads the conversation on screen.
    get.mockClear();
    act(() => voiceCall.options.onTurnSaved?.());
    expect(get).not.toHaveBeenCalledWith(
      "/conversations/c-b/messages?latest=true&limit=101&top_level_only=true",
    );
  });

  it("hangs up a call started in a new chat when another conversation is opened before it is named", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();
    fireEvent.click(await offeredCall());
    act(() => useConversationStore.getState().setCurrentConversationId("c-b"));
    expect(voiceCall.end).toHaveBeenCalled();
    // The server naming the call's conversation afterwards does not pull the person back.
    act(() => voiceCall.options.onConversation?.("c-new"));
    expect(useConversationStore.getState().currentConversationId).toBe("c-b");
  });

  /** The container, and a way to draw it again once the test changed the call. */
  function mountRedrawable() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = () => (
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>
    );
    const view = render(tree());
    return () => view.rerender(tree());
  }

  it("puts focus back on the call button when the call ends, if the bar took it with it", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = LIVE_CALL;
    const redraw = mountRedrawable();
    await offeredCall();
    expect(await screen.findByRole("group", { name: "Voice call" })).toHaveFocus();
    voiceCall.call = { ...LIVE_CALL, phase: "ended", endReason: "user", endedAt: Date.now() };
    act(() => redraw());
    expect(screen.getByRole("button", { name: "Start a voice call" })).toHaveFocus();
  });

  it("leaves focus where the person put it during the call", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = LIVE_CALL;
    const redraw = mountRedrawable();
    await offeredCall();
    const elsewhere = document.createElement("input");
    document.body.appendChild(elsewhere);
    elsewhere.focus();
    voiceCall.call = { ...LIVE_CALL, phase: "ended", endReason: "user", endedAt: Date.now() };
    act(() => redraw());
    expect(elsewhere).toHaveFocus();
    elsewhere.remove();
  });

  it("goes to the message box after ending a call to continue in text", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = {
      ...LIVE_CALL,
      approvalUnavailable: { tool: "send_invoice", args: { customer: "Acme" } },
    };
    const redraw = mountRedrawable();
    await offeredCall();
    fireEvent.click(screen.getByRole("button", { name: "End call, continue in text" }));
    expect(voiceCall.end).toHaveBeenCalled();
    voiceCall.call = { ...LIVE_CALL, phase: "ended", endReason: "user", endedAt: Date.now() };
    act(() => redraw());
    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("shows the call's turns as they are spoken, without an empty state behind them", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = {
      ...LIVE_CALL,
      captions: [{ turnId: "c1:1:user", part: 0, role: "user", text: "Hello there", final: false }],
    };
    mount();
    expect(await screen.findByTestId("voice-captions-visible")).toHaveTextContent("Hello there");
  });
});

describe("the chat container - where an empty conversation is scrolled", () => {
  it("holds a welcome at its top and follows the foot once a turn starts", async () => {
    // In the Architect's narrow window the welcome is taller than the pane, and
    // following the foot of an empty conversation scrolled its greeting and the
    // face above it out of view.
    const observers = observeSizes();
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
    const dock = screen.getByRole("textbox").closest("[data-chat-dock]") as HTMLElement;
    const scroller = dock.previousElementSibling as HTMLElement;
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1500 });
    const follow = observers.find(
      (observer) => observer.targets.includes(scroller) && !observer.targets.includes(dock),
    )!;
    act(() => follow.grew());
    expect(scroller.scrollTop).toBe(1500);
    expect(scrollTo).not.toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
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
    loadTranscript([
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
      if (url === `/conversations/${LEFT}/messages?latest=true&limit=101&top_level_only=true`) {
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
      if (url === "/conversations/background-tasks") return Promise.resolve([]);
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("uses the persisted run start for a resumed stream and its sidebar clock", async () => {
    useConversationStore.getState().setCurrentConversationId(LEFT);
    const started = running!;
    loadTranscript([
      {
        id: "clock-question",
        conversation_id: LEFT,
        role: "user",
        content: "Check the project",
        created_at: new Date().toISOString(),
      },
    ]);
    mount();
    await screen.findByText(/still answering when you left/);
    receive("turn_attached", { conversation_id: LEFT });
    receive("model_request_start", {});
    receive("tool_call", { tool_name: "get_project", args: {}, tool_call_id: "read-1" });
    await waitFor(() => expect(useWorkingStore.getState().since[LEFT]).toBe(started));
  });

  it("says the agent is still answering, and fetches the answer when its run ends", async () => {
    // The thread as a reload finds it: the question, and nothing after it.
    useConversationStore.getState().setCurrentConversationId(LEFT);
    loadTranscript([
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
    const reads = () =>
      get.mock.calls.filter(
        ([url]) =>
          url === `/conversations/${LEFT}/messages?latest=true&limit=101&top_level_only=true`,
      );
    const before = reads().length;
    const question = screen.getByText("Write me a rollout plan");
    const observedLengths: number[] = [];
    const unsubscribe = useChatStore.subscribe((state) =>
      observedLengths.push(state.messages.length),
    );

    // The run ends: the next read of the list no longer says it is at work.
    running = null;
    await act(async () => {
      await client.invalidateQueries();
    });

    try {
      await vi.waitFor(() => expect(reads().length).toBeGreaterThan(before), SETTLE);
      expect(observedLengths).not.toContain(0);
      expect(screen.getByText("Write me a rollout plan")).toBe(question);
    } finally {
      unsubscribe();
    }
  });

  it("says nothing of an answer left behind while this tab holds the call that is the run", async () => {
    // A call is a run in its conversation, and while the agent thinks the last
    // spoken turn is the caller's: that is not a turn somebody walked away from.
    voiceCall.call = { ...initialCall, phase: "live", callId: "call-1", startedAt: Date.now() };
    useConversationStore.getState().setCurrentConversationId(LEFT);
    loadTranscript([
      {
        id: "m-1",
        conversation_id: LEFT,
        role: "user",
        content: "Write me a rollout plan",
        created_at: new Date().toISOString(),
      },
    ]);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChatContainer />
      </QueryClientProvider>,
    );

    // The list that says the run is at work has been read.
    await vi.waitFor(
      () =>
        expect(get.mock.calls.some(([url]) => String(url).startsWith("/conversations?"))).toBe(
          true,
        ),
      SETTLE,
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(screen.queryByText(/still answering when you left/)).toBeNull();
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
    loadTranscript([
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

  it("says the answer was lost when its run ended without one, and asks again", async () => {
    // The process running the turn died; the stale-run sweep closed the run and
    // nothing was ever written after the question (#2301).
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    useConversationStore.getState().setCurrentConversationId(LEFT);
    loadTranscript([
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

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      running = null;
      await act(async () => {
        await client.invalidateQueries();
      });
      // Every re-read the chat makes for a landing answer, and none lands.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });

      expect(screen.getByText(/stopped before it answered/)).toBeInTheDocument();
      expect(screen.queryByText(/still answering when you left/)).toBeNull();
      socket.send.mockClear();
      fireEvent.click(screen.getByRole("button", { name: "Ask again" }));
      expect(
        socket.send.mock.calls.some(([frame]) =>
          JSON.stringify(frame).includes("Write me a rollout plan"),
        ),
      ).toBe(true);
    } finally {
      vi.useRealTimers();
    }
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

describe("the chat container - late transcript reconciliation", () => {
  function stored(id: string, role: "user" | "assistant", content: string) {
    return { id, role, content, conversation_id: "c-race", created_at: "2026-10-01T12:00:00Z" };
  }

  it("revalidates a live first turn when its tenant resolves without losing pending text", async () => {
    useOrgStore.setState({ activeOrgId: null });
    let finishOrganizations!: (value: unknown) => void;
    let finishHistory!: (value: unknown) => void;
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => {
      if (url === "/orgs")
        return new Promise((resolve) => {
          finishOrganizations = resolve;
        });
      if (url.startsWith("/conversations/c-new/messages"))
        return new Promise((resolve) => {
          finishHistory = resolve;
        });
      return base(url);
    });
    mount();
    await waitFor(() => expect(finishOrganizations).toBeDefined());
    receive("conversation_created", { conversation_id: "c-new" });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Before resolution" });
    expect(useChatStore.getState().loadedTranscript?.tenantId).toBeNull();

    await act(async () =>
      finishOrganizations({
        items: [{ id: "org-1", name: "Default", is_personal: true }],
        total: 1,
      }),
    );
    await waitFor(() => expect(finishHistory).toBeDefined());
    receive("text_delta", { index: 0, content: " while validating" });
    await act(async () => finishHistory({ items: [], total: 0, cost: null }));
    receive("text_delta", { index: 0, content: " after validation" });
    expect(useChatStore.getState().messages.at(-1)?.content).toBe(
      "Before resolution while validating after validation",
    );
    expect(useChatStore.getState().loadedTranscript?.tenantId).toBe("org-1");
    expect(
      get.mock.calls.filter(([url]) => String(url).startsWith("/conversations/c-new/messages")),
    ).toHaveLength(1);
  });

  it("does not attach unresolved live history when concrete-tenant revalidation is refused", async () => {
    useOrgStore.setState({ activeOrgId: null });
    let finishOrganizations!: (value: unknown) => void;
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => {
      if (url === "/orgs")
        return new Promise((resolve) => {
          finishOrganizations = resolve;
        });
      if (url.startsWith("/conversations/c-new/messages"))
        return Promise.reject(new Error("refused"));
      return base(url);
    });
    mount();
    await waitFor(() => expect(finishOrganizations).toBeDefined());
    receive("conversation_created", { conversation_id: "c-new" });
    socket.send.mockClear();
    await act(async () =>
      finishOrganizations({
        items: [{ id: "org-1", name: "Default", is_personal: true }],
        total: 1,
      }),
    );
    await waitFor(() =>
      expect(
        get.mock.calls.some(([url]) => String(url).startsWith("/conversations/c-new/messages")),
      ).toBe(true),
    );
    act(() => {
      socket.isConnected = false;
      useChatStore.setState({ messages: [...useChatStore.getState().messages] });
    });
    act(() => {
      socket.isConnected = true;
      useChatStore.setState({ messages: [...useChatStore.getState().messages] });
    });
    expect(socket.send).not.toHaveBeenCalledWith({ type: "attach", conversation_id: "c-new" });
    expect(useChatStore.getState().loadedTranscript?.tenantId).toBeNull();
    expect(
      get.mock.calls.filter(([url]) => String(url).startsWith("/conversations/c-new/messages")),
    ).toHaveLength(1);
  });

  async function openQuestion() {
    useConversationStore.getState().setCurrentConversationId("c-race");
    loadTranscript([stored("question", "user", "Initial question")]);
    mount();
    await screen.findByText("Initial question");
    receive("turn_attached", { conversation_id: "c-race" });
    receive("model_request_start", {});
  }

  it("keeps the next streamed bubble when the previous turn's late history lands", async () => {
    await openQuestion();
    receive("text_delta", { index: 0, content: "First answer" });
    receive("message_saved", { message_id: "first-answer" });
    receive("complete", {});
    let finish!: (value: unknown) => void;
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) =>
      path.includes("/messages")
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : fallback(path),
    );
    receive("turn_followed_to_end", { conversation_id: "c-race" });
    receive("turn_attached", { conversation_id: "c-race" });
    receive("turn_prompt", {
      conversation_id: "c-race",
      message_id: "second-question",
      content: "Next question",
      sender: { user_id: "u-1", name: "Kacper" },
    });
    receive("model_request_start", {});
    receive("text_delta", { index: 0, content: "Second answer" });
    await act(async () =>
      finish({
        items: [
          stored("question", "user", "Initial question"),
          stored("first-answer", "assistant", "First answer"),
        ],
        total: 2,
        cost: null,
      }),
    );
    receive("text_delta", { index: 0, content: " continues" });
    expect(useChatStore.getState().messages.at(-1)?.content).toBe("Second answer continues");
    receive("final_result", { output: "Second answer continues" });
    receive("complete", {});
    expect(await screen.findByText("Second answer continues")).toBeVisible();
  });

  it("renders one prompt and answer when a transcript recovers a lost persistence acknowledgement", async () => {
    const sender = { user_id: "u-1", name: "Kacper", has_avatar: false, avatar_color: null };
    useConversationStore.getState().setCurrentConversationId("c-race");
    loadTranscript([stored("anchor", "user", "Earlier")]);
    mount();
    await screen.findByText("Earlier");
    act(() => {
      useChatStore.getState().addMessage({
        id: "local-question",
        role: "user",
        content: "Question after reconnect",
        timestamp: new Date(),
        conversationId: "c-race",
        sender,
        clientMessageId: "nonce",
        isTemporaryId: true,
      });
      useChatStore.getState().addMessage({
        id: "local-answer",
        role: "assistant",
        content: "Partial result",
        timestamp: new Date(),
        conversationId: "c-race",
        isTemporaryId: true,
      });
    });
    act(() =>
      loadTranscript([
        stored("anchor", "user", "Earlier"),
        {
          ...stored("saved-question", "user", "Question after reconnect"),
          sender,
          client_message_id: "nonce",
        },
        stored("saved-answer", "assistant", "Finished result"),
      ]),
    );
    expect(await screen.findByText("Finished result")).toBeVisible();
    expect(screen.getAllByText("Question after reconnect")).toHaveLength(1);
    expect(screen.queryByText("Partial result")).not.toBeInTheDocument();
    expect(useChatStore.getState().messages.map((message) => message.id)).toEqual([
      "anchor",
      "saved-question",
      "saved-answer",
    ]);
  });

  it("retains an unsaved result and its error when following ends", async () => {
    await openQuestion();
    receive("text_delta", { index: 0, content: "Unsaved answer" });
    receive("error", { message: "Could not persist this answer" });
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) =>
      path.includes("/messages")
        ? Promise.resolve({
            items: [stored("question", "user", "Initial question")],
            total: 1,
            cost: null,
          })
        : fallback(path),
    );
    receive("complete", {});
    receive("turn_followed_to_end", { conversation_id: "c-race" });
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        expect.stringContaining("/conversations/c-race/messages?latest=true"),
      ),
    );
    await act(async () => {});
    expect(useChatStore.getState().messages.at(-1)?.content).toContain("Unsaved answer");
    expect(useChatStore.getState().messages.at(-1)).toMatchObject({
      runFailed: true,
      runError: "Could not persist this answer",
    });
    expect(await screen.findByText(/Could not persist this answer/)).toBeVisible();
  });
});

describe("personal message pins in chat", () => {
  function openPins(sharePermission?: "view") {
    const conversation = {
      id: "c-pins",
      title: "Saved discussion",
      user_id: sharePermission ? "another-reader" : SIGNED_IN.id,
      share_permission: sharePermission,
      is_archived: false,
    };
    const pin = {
      message_id: "older-pin",
      thread_root_message_id: "older-root",
      role: "assistant",
      message_created_at: "2026-10-01T12:00:00Z",
      pinned_at: "2026-11-17T00:00:00Z",
      preview: "An older bookmarked answer",
    };
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) =>
      path === "/conversations/c-pins/metadata"
        ? Promise.resolve(conversation)
        : path.startsWith("/conversations?")
          ? Promise.resolve({ items: sharePermission ? [] : [conversation], total: 1 })
          : path === "/conversations/c-pins/message-pins"
            ? Promise.resolve({ items: [pin], total: 1 })
            : fallback(path),
    );
    useConversationStore.getState().setCurrentConversationId("c-pins");
    loadTranscript([
      {
        id: "current-pin",
        conversation_id: "c-pins",
        role: "user",
        content: "A message worth keeping",
        created_at: "2026-11-17T00:00:00Z",
        is_pinned: false,
      },
    ]);
    vi.mocked(apiClient.post).mockResolvedValue(pin);
  }

  it("pins the saved message and lazily opens an exact room-reply bookmark", async () => {
    openPins();
    const onOpen = vi.fn();
    mount("c-pins", undefined, undefined, onOpen);
    await userEvent.click(await screen.findByRole("button", { name: "Pin message" }));
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-pins/messages/current-pin/pin");
    expect(await screen.findByRole("button", { name: "Unpin message" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(get.mock.calls.some(([path]) => String(path).endsWith("/message-pins"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Pinned messages" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "An older bookmarked answer" }),
    );
    expect(onOpen).toHaveBeenCalledExactlyOnceWith({
      conversationId: "c-pins",
      messageId: "older-pin",
      threadRootMessageId: "older-root",
    });
  });

  it("lets a read-only recipient keep a private pin", async () => {
    openPins("view");
    mount("c-pins", undefined, undefined, vi.fn());
    await screen.findByText("Shared with you as read-only");
    expect(screen.queryByRole("button", { name: "Reply" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Pin message" }));
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-pins/messages/current-pin/pin");
  });

  it("hides pin actions when a fresh access read refuses cached history", async () => {
    openPins("view");
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) =>
      path === "/conversations/c-pins/metadata"
        ? Promise.reject(new Error("Access changed"))
        : fallback(path),
    );
    mount("c-pins", undefined, "current-pin", vi.fn());
    await screen.findByText("The selected message could not be loaded. Try again.");
    expect(screen.queryByRole("button", { name: "Pin message" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pinned messages/ })).not.toBeInTheDocument();
    expect(get.mock.calls.some(([path]) => String(path).endsWith("/message-pins"))).toBe(false);
  });
});

describe("manual compaction in the chat surface", () => {
  function openCompactableChat(shared = false) {
    const conversation = {
      id: "c-compact",
      title: "Long discussion",
      user_id: shared ? "another-reader" : SIGNED_IN.id,
      share_permission: shared ? "view" : undefined,
      is_archived: false,
      project_id: null,
    };
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) => {
      if (path.startsWith("/conversations/c-compact/compaction-availability"))
        return Promise.resolve({ available: true });
      if (path === "/conversations/c-compact/metadata") return Promise.resolve(conversation);
      if (path.startsWith("/conversations?"))
        return Promise.resolve({ items: shared ? [] : [conversation], total: 1 });
      if (path.startsWith("/agents") && !path.includes("/dictation") && !path.includes("/voice"))
        return Promise.resolve({
          items: [
            {
              id: "compact-agent",
              slug: "compact-agent",
              name: "Compaction agent",
              status: "published",
              can_run: true,
            },
          ],
          total: 1,
        });
      if (path === "/agents/compact-agent/voice")
        return Promise.resolve({ available: true, transport: "webrtc" });
      return fallback(path);
    });
    useAgentSelectionStore.setState({ selectedAgentId: "compact-agent" });
    useConversationStore.getState().setCurrentConversationId("c-compact");
    loadTranscript([
      {
        id: "saved-question",
        conversation_id: "c-compact",
        role: "user",
        content: "Earlier question",
        created_at: "2026-11-17T00:00:00Z",
      },
      {
        id: "saved-answer",
        conversation_id: "c-compact",
        role: "assistant",
        content: "Earlier answer",
        created_at: "2026-11-17T00:00:01Z",
      },
    ]);
    socket.send.mockReturnValue(true);
    mount("c-compact");
  }

  afterEach(() => socket.send.mockReset());

  it("compacts without submitting or clearing the draft and reports correlated progress", async () => {
    openCompactableChat();
    const compact = await screen.findByRole("button", { name: "Compact now" });
    receive("session_ready", {});
    await waitFor(() => expect(compact).toBeEnabled());
    const editor = screen.getByRole("textbox");
    await userEvent.type(editor, "Keep this draft");
    await userEvent.click(compact);

    const request = socket.send.mock.calls
      .map(([frame]) => frame as Record<string, unknown>)
      .find((frame) => frame.type === "compact_now");
    expect(request).toMatchObject({ conversation_id: "c-compact", agent_id: "compact-agent" });
    expect(typeof request?.request_id).toBe("string");
    expect(compact).toBeDisabled();
    expect(messageOf(editor)).toBe("Keep this draft");
    expect(socket.send.mock.calls.some(([frame]) => frame.message)).toBe(false);
    expect(useChatStore.getState().messages).toHaveLength(2);
    act(() => useComposerIntentStore.setState({ intent: "call" }));
    expect(voiceCall.start).not.toHaveBeenCalled();

    receive("compaction_started", { request_id: request!.request_id, messages_before: 12 });
    expect(await screen.findByText(/Summarizing 12 earlier messages/)).toBeVisible();
    receive("compact_now_result", {
      request_id: request!.request_id,
      conversation_id: "c-compact",
      status: "compacted",
    });
    receive("session_ready", {});
    expect(await screen.findByText(/Context compacted/)).toBeVisible();
    expect(compact).toBeEnabled();
    expect(messageOf(editor)).toBe("Keep this draft");
    expect(useChatStore.getState().messages).toHaveLength(2);
  });

  it("disables manual compaction while the conversation is answering", async () => {
    openCompactableChat();
    const compact = await screen.findByRole("button", { name: "Compact now" });
    receive("session_ready", {});
    await waitFor(() => expect(compact).toBeEnabled());
    await userEvent.type(screen.getByRole("textbox"), "A follow-up{Enter}");
    await waitFor(() =>
      expect(socket.send.mock.calls.some(([frame]) => frame.message === "A follow-up")).toBe(true),
    );
    await waitFor(() => expect(compact).toBeDisabled());
    await userEvent.click(compact);
    expect(socket.send.mock.calls.some(([frame]) => frame.type === "compact_now")).toBe(false);
  });

  it("keeps Stop available during manual compaction and waits for cleanup", async () => {
    openCompactableChat();
    const compact = await screen.findByRole("button", { name: "Compact now" });
    receive("session_ready", {});
    await waitFor(() => expect(compact).toBeEnabled());
    await userEvent.click(compact);
    const request = socket.send.mock.calls
      .map(([frame]) => frame as Record<string, unknown>)
      .find((frame) => frame.type === "compact_now");
    const stop = await screen.findByRole("button", { name: /^Stop/ });
    expect(stop).toBeEnabled();
    await userEvent.click(stop);
    expect(socket.send).toHaveBeenCalledWith({ type: "stop" });
    receive("compact_now_result", {
      request_id: request!.request_id,
      conversation_id: "c-compact",
      status: "failed",
    });
    expect(compact).toBeDisabled();
    receive("session_ready", {});
    await waitFor(() => expect(compact).toBeEnabled());
    expect(useChatStore.getState().messages).toHaveLength(2);
    expect(socket.send.mock.calls.some(([frame]) => frame.message)).toBe(false);
  });

  it("hides manual compaction for a read-only shared conversation", async () => {
    openCompactableChat(true);
    await screen.findByText("Shared with you as read-only");
    expect(screen.queryByRole("button", { name: "Compact now" })).not.toBeInTheDocument();
    expect(socket.send.mock.calls.some(([frame]) => frame.type === "compact_now")).toBe(false);
  });
});

it("follows an exact main-chat link through older history and preserves the current page", async () => {
  const current = {
    id: "m-2",
    role: "user" as const,
    content: "Current page",
    conversation_id: "paged",
    created_at: "2026-10-01T12:00:00Z",
  };
  useConversationStore.getState().setCurrentConversationId("paged");
  loadTranscript([current], null, true);
  const fallback = get.getMockImplementation()!;
  get.mockImplementation((path: string) =>
    path.includes("before=m-2")
      ? Promise.resolve({
          items: [{ ...current, id: "m-1", content: "Linked earlier page" }],
          total: 2,
          cost: null,
        })
      : fallback(path),
  );
  mount("paged", undefined, "m-1");
  await screen.findByText("Linked earlier page");
  await waitFor(() => expect(document.querySelector('[data-message-id="m-1"]')).toHaveFocus());
  expect(screen.getByText("Current page")).toBeVisible();
  expect(get.mock.calls.filter(([path]) => String(path).includes("before=m-2"))).toHaveLength(1);
});

it("reveals a linked segment inside a combined saved turn", async () => {
  const first = {
    id: "segment-a",
    role: "assistant" as const,
    content: "Earlier saved segment",
    conversation_id: "combined",
    run_id: "shared-run",
    created_at: "2026-10-01T12:00:00Z",
  };
  useConversationStore.getState().setCurrentConversationId("combined");
  loadTranscript([first, { ...first, id: "segment-b", content: "Final saved answer" }]);
  mount("combined", undefined, "segment-a");
  await waitFor(() =>
    expect(document.querySelector('[data-message-ids~="segment-a"]')).toHaveFocus(),
  );
  expect(await screen.findByText("Earlier saved segment")).toBeVisible();
  expect(screen.getByText("Final saved answer")).toBeVisible();
});

it("does not load older linked history after the access read is refused", async () => {
  const current = {
    id: "m-2",
    role: "user" as const,
    content: "Cached page",
    conversation_id: "denied",
    created_at: "2026-10-01T12:00:00Z",
  };
  useConversationStore.getState().setCurrentConversationId("denied");
  loadTranscript([current], null, true);
  const fallback = get.getMockImplementation()!;
  get.mockImplementation((path: string) =>
    path === "/conversations/denied/metadata"
      ? Promise.reject(new Error("Access changed"))
      : fallback(path),
  );
  mount("denied", undefined, "old-message");
  await screen.findByText("The selected message could not be loaded. Try again.");
  expect(get.mock.calls.some(([path]) => String(path).includes("before="))).toBe(false);
});

it("loads earlier messages from the transcript control without losing the current page", async () => {
  const current = {
    id: "m-2",
    role: "user" as const,
    content: "Current page",
    conversation_id: "paged",
    created_at: "2026-10-01T12:00:00Z",
  };
  useConversationStore.getState().setCurrentConversationId("paged");
  loadTranscript([current], null, true);
  const fallback = get.getMockImplementation()!;
  let finish!: (value: unknown) => void;
  get.mockImplementation((path: string) =>
    path.includes("before=m-2")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : fallback(path),
  );
  mount();
  const button = await screen.findByRole("button", { name: "Load earlier messages" });
  fireEvent.click(button);
  expect(button).toBeDisabled();
  await act(async () =>
    finish({ items: [{ ...current, id: "m-1", content: "Earlier page" }], total: 2, cost: null }),
  );
  expect(await screen.findByText("Earlier page")).toBeVisible();
  expect(screen.getByText("Current page")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Load earlier messages" })).not.toBeInTheDocument();
});

describe("routine answers arriving in the open source conversation", () => {
  it("rereads a matching private delivery in place and deduplicates repeated announcements", async () => {
    const original = {
      id: "before-routine",
      run_id: "worker-run",
      role: "assistant",
      content: "Already here",
      conversation_id: "source-chat",
      created_at: "2026-11-02T10:00:00Z",
    };
    useConversationStore.getState().setCurrentConversationId("source-chat");
    loadTranscript([original] as never);
    let deliveredText = "Approved routine result";
    const fallback = get.getMockImplementation()!;
    get.mockImplementation((path: string) =>
      path.startsWith("/conversations/source-chat/messages")
        ? Promise.resolve({
            items: [original, { ...original, id: "routine-result", content: deliveredText }],
            total: 2,
            cost: null,
          })
        : fallback(path),
    );
    mount();
    await screen.findByText("Already here");
    const delivered: ChangeEvent = {
      organization_id: "org-1",
      resource: "conversation",
      id: "source-chat",
      action: "updated",
      surface: "run",
      actor_user_id: "u-1",
      actor_name: null,
      origin_tab: null,
    };
    await act(async () => announceChange({ ...delivered, id: "another-chat" }));
    expect(screen.queryByText("Approved routine result")).not.toBeInTheDocument();
    await act(async () => announceChange({ ...delivered, organization_id: "other-org" }));
    expect(screen.queryByText("Approved routine result")).not.toBeInTheDocument();
    await act(async () => announceChange(delivered));
    expect(await screen.findByText("Approved routine result")).toBeVisible();
    await act(async () => announceChange(delivered));
    await waitFor(() => expect(screen.getAllByText("Approved routine result")).toHaveLength(1));
    deliveredText = "Worker continuation reached another approval";
    await act(async () => announceChange({ ...delivered, resource: "run", id: "worker-run" }));
    expect(await screen.findByText(deliveredText)).toBeVisible();
    expect(useConversationStore.getState().currentConversationId).toBe("source-chat");
  });
});

it("keeps the draft focused when tapping dock buttons while leaving keyboard focus available", async () => {
  mount();
  const editor = await screen.findByRole("textbox", { name: "Type a message..." });
  await userEvent.type(editor, "An unsent phone draft");
  const send = screen.getByRole("button", { name: "Send message" });
  expect(editor).toHaveFocus();
  expect(fireEvent.mouseDown(send)).toBe(false);
  expect(editor).toHaveFocus();
  act(() => send.focus());
  expect(send).toHaveFocus();
  expect(messageOf(editor)).toBe("An unsent phone draft");
});

describe("the chat container - forking a conversation (#2762)", () => {
  function listOwnedBy(
    owner: string,
    forkedFrom: unknown = null,
    sideForks: ConversationForkRead[] = [],
  ) {
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => {
      if (url === "/conversations/c-mine/forks")
        return Promise.resolve({ items: sideForks, total: sideForks.length });
      return url.startsWith("/conversations?")
        ? Promise.resolve({
            items: [{ id: "c-mine", title: "Pricing", user_id: owner, forked_from: forkedFrom }],
            total: 1,
          })
        : base(url);
    });
    useConversationStore.getState().setCurrentConversationId("c-mine");
    loadTranscript([
      {
        id: "m-answer",
        conversation_id: "c-mine",
        role: "assistant",
        content: "Start at 10.",
        created_at: "2026-11-06T10:00:00Z",
      },
    ] as never);
  }

  it("lets the owner fork at an answer, and opens the fork", async () => {
    listOwnedBy(SIGNED_IN.id);
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c-fork", title: "Pricing" });
    mount();

    await userEvent.click(
      await screen.findByRole("button", { name: "Fork into a new conversation" }, SETTLE),
    );

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-mine/fork", {
        message_id: "m-answer",
      }),
    );
    await waitFor(() =>
      expect(useConversationStore.getState().currentConversationId).toBe("c-fork"),
    );
  });

  it("names where the owner's fork came from, and opens it", async () => {
    listOwnedBy(SIGNED_IN.id, { conversation_id: "c-source", message_id: "m-1", title: "Plans" });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Plans" }, SETTLE));

    await waitFor(() =>
      expect(useConversationStore.getState().currentConversationId).toBe("c-source"),
    );
  });

  it("starts one fork however often it is clicked while that one is being made", async () => {
    listOwnedBy(SIGNED_IN.id);
    let finish: (value: unknown) => void = () => undefined;
    vi.mocked(apiClient.post).mockReturnValue(new Promise((resolve) => (finish = resolve)));
    mount();
    const fork = await screen.findByRole(
      "button",
      { name: "Fork into a new conversation" },
      SETTLE,
    );

    await userEvent.click(fork);
    expect(fork).toBeDisabled();
    expect(fork).toHaveAttribute("aria-busy", "true");
    await userEvent.click(fork);
    finish({ id: "c-fork", title: "Pricing" });

    await waitFor(() =>
      expect(useConversationStore.getState().currentConversationId).toBe("c-fork"),
    );
    expect(
      vi.mocked(apiClient.post).mock.calls.filter(([path]) => String(path).endsWith("/fork")),
    ).toHaveLength(1);
  });

  it("offers no fork in somebody else's thread", async () => {
    listOwnedBy("someone-else");
    mount();

    await screen.findByText("Start at 10.", undefined, SETTLE);
    expect(screen.queryByRole("button", { name: "Fork into a new conversation" })).toBeNull();
  });

  it("creates a side thread in its own scope without switching the main transcript or URL", async () => {
    listOwnedBy(SIGNED_IN.id);
    const child: ConversationForkRead = {
      id: "c-side",
      title: "Alternative path",
      created_at: "2026-11-17T12:00:00Z",
      updated_at: null,
      is_archived: false,
      forked_from: {
        conversation_id: "c-mine",
        message_id: "m-answer",
        title: "Pricing",
      },
    };
    vi.mocked(apiClient.post).mockImplementation((path: string) =>
      path === "/conversations/c-mine/fork" ? Promise.resolve(child) : Promise.resolve(undefined),
    );
    mount();
    const mainMessages = structuredClone(useConversationStore.getState().currentMessages);
    const address = window.location.href;

    await userEvent.click(await screen.findByRole("button", { name: "Side threads" }, SETTLE));
    await userEvent.click(await screen.findByRole("button", { name: "Start a side thread" }));

    await screen.findByRole("dialog", { name: "Alternative path" }, SETTLE);
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-mine/fork", {
        message_id: "m-answer",
      }),
    );
    expect(useConversationStore.getState().currentConversationId).toBe("c-mine");
    expect(useConversationStore.getState().currentMessages).toEqual(mainMessages);
    expect(window.location.href).toBe(address);

    await userEvent.click(screen.getByRole("button", { name: "Close side thread" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Alternative path" })).toBeNull(),
    );
    expect(useConversationStore.getState().currentConversationId).toBe("c-mine");
    expect(useConversationStore.getState().currentMessages).toEqual(mainMessages);
    expect(window.location.href).toBe(address);
  });

  it("opens an existing child from only its exact answer without selecting it in the main chat", async () => {
    const child: ConversationForkRead = {
      id: "c-side",
      title: "Alternative path",
      created_at: "2026-11-17T12:00:00Z",
      updated_at: null,
      is_archived: true,
      forked_from: {
        conversation_id: "c-mine",
        message_id: "m-answer",
        title: "Pricing",
      },
    };
    listOwnedBy(SIGNED_IN.id, null, [child]);
    mount();
    const mainMessages = structuredClone(useConversationStore.getState().currentMessages);
    const address = window.location.href;

    await userEvent.click(await screen.findByRole("button", { name: "Side threads" }, SETTLE));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/conversations/c-mine/forks", {
        params: { message_id: "m-answer", skip: "0", limit: "100" },
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /Alternative path/ }));

    await screen.findByRole("dialog", { name: "Alternative path" }, SETTLE);
    expect(useConversationStore.getState().currentConversationId).toBe("c-mine");
    expect(useConversationStore.getState().currentMessages).toEqual(mainMessages);
    expect(window.location.href).toBe(address);
  });

  it("jumps back to the exact parent answer without restoring focus to the side-thread opener", async () => {
    const child: ConversationForkRead = {
      id: "c-side",
      title: "Alternative path",
      created_at: "2026-11-17T12:00:00Z",
      updated_at: null,
      is_archived: false,
      forked_from: {
        conversation_id: "c-mine",
        message_id: "m-answer",
        title: "Pricing",
      },
    };
    listOwnedBy(SIGNED_IN.id, null, [child]);
    const onOpenParent = vi.fn(() => document.getElementById("parent-message-anchor")?.focus());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <button type="button">Main chat</button>
        <div id="parent-message-anchor" tabIndex={-1} />
        <ChatContainer onOpenParent={onOpenParent} />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Side threads" }, SETTLE));
    await userEvent.click(await screen.findByRole("button", { name: /Alternative path/ }));
    await screen.findByRole("dialog", { name: "Alternative path" }, SETTLE);
    await userEvent.click(screen.getByRole("button", { name: "Back to parent conversation" }));

    await waitFor(() =>
      expect(onOpenParent).toHaveBeenCalledExactlyOnceWith({
        conversationId: "c-mine",
        messageId: "m-answer",
      }),
    );
    expect(document.getElementById("parent-message-anchor")).toHaveFocus();
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Alternative path" })).toBeNull(),
    );
  });
});

describe("the chat container - a conversation shared with the reader", () => {
  /** Open a conversation the reader's own listing does not hold, as its metadata describes it. */
  function openShared(metadata: Record<string, unknown> | Promise<never>) {
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/conversations/c-theirs/metadata"
        ? metadata instanceof Promise
          ? metadata
          : Promise.resolve({ id: "c-theirs", title: "Their plan", ...metadata })
        : url.startsWith("/conversations?")
          ? Promise.resolve({ items: [], total: 0 })
          : base(url),
    );
    useConversationStore.getState().setCurrentConversationId("c-theirs");
    loadTranscript([
      {
        id: "m-1",
        conversation_id: "c-theirs",
        role: "assistant",
        content: "Here is the plan.",
        created_at: "2026-11-06T10:00:00Z",
      },
    ] as never);
  }

  it("disables a pending approval after the thread becomes read-only", async () => {
    openShared({ share_permission: "view", is_archived: false });
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/me/permissions"
        ? Promise.resolve({
            organization_id: "org-1",
            role: "admin",
            permissions: [{ permission: "approvals:decide", scope: "all" }],
          })
        : base(url),
    );
    mount();
    await screen.findByText("Shared with you as read-only", undefined, SETTLE);
    receive("tool_approval_required", {
      run_id: "shared-run",
      action_requests: [
        { id: "approval", tool_call_id: "send", tool_name: "send_email", args: {} },
      ],
      review_configs: [],
    });
    expect(await screen.findByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("offers no message box to somebody it was shared with to read", async () => {
    openShared({ share_permission: "view", is_archived: false });
    mount();

    expect(
      await screen.findByText("Shared with you as read-only", undefined, SETTLE),
    ).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    receive("conversation_created", { conversation_id: "c-theirs" });
    expect(useConversationStore.getState().createdConversationId).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
  });

  it("keeps the message box for somebody it was shared with to edit", async () => {
    openShared({ share_permission: "edit", is_archived: false });
    mount();

    await waitFor(
      () => expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-disabled", "true"),
      SETTLE,
    );
    expect(screen.queryByText("Shared with you as read-only")).toBeNull();
  });

  it("says an archived shared thread is archived, even to somebody who may edit it", async () => {
    openShared({ share_permission: "edit", is_archived: true });
    mount();

    expect(
      await screen.findByText("This conversation is archived", undefined, SETTLE),
    ).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-disabled", "true");
  });

  it("lets nothing be written before it knows what the reader may do", async () => {
    openShared(new Promise<never>(() => {}));
    mount();

    expect(
      await screen.findByText("Checking conversation access…", undefined, SETTLE),
    ).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    // Not archived, and not said to be: it is only not known yet.
    expect(screen.queryByText("This conversation is archived")).toBeNull();
  });

  it("keeps access failures visible and offers a retry without enabling writes", async () => {
    openShared(Promise.reject(new Error("offline")) as Promise<never>);
    mount();

    expect(
      await screen.findByText("Could not verify access to this conversation", undefined, SETTLE),
    ).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    const previous = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url === "/conversations/c-theirs/metadata"
        ? Promise.resolve({ id: "c-theirs", share_permission: "edit", is_archived: false })
        : previous(url),
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(
      () => expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-disabled", "true"),
      SETTLE,
    );
    expect(screen.queryByText("Could not verify access to this conversation")).toBeNull();
  });

  it("offers fork controls and lineage for an owned chat beyond the sidebar page", async () => {
    openShared({
      user_id: SIGNED_IN.id,
      share_permission: null,
      is_archived: false,
      forked_from: { conversation_id: "c-source", message_id: "m-source", title: "Earlier plan" },
    });
    mount();

    expect(
      await screen.findByRole("button", { name: "Fork into a new conversation" }, SETTLE),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Earlier plan" })).toBeVisible();
  });
});

it("keeps actionable outcome notices beside the composer instead of above the transcript", async () => {
  const originalGet = get.getMockImplementation();
  get.mockImplementation((url: string, ...args: unknown[]) =>
    url.startsWith("/outcomes?")
      ? Promise.resolve({
          items: [
            {
              id: "notice",
              kind: "approval_requested",
              summary: "Review the pending operation",
              status: "open",
              context_url: "/runs?tab=approvals",
              source_conversation_id: "c-notice",
            },
          ],
        })
      : originalGet?.(url, ...args),
  );
  useConversationStore.getState().setCurrentConversationId("c-notice");
  mount();
  const notice = await screen.findByText("Review the pending operation");
  const dock = screen.getByRole("textbox").closest("[data-chat-dock]");
  expect(dock).toContainElement(notice);
  expect(document.querySelector("[data-transcript]")).not.toContainElement(notice);
});

describe("opening a saved chat", () => {
  it("never shows welcome prompts while the requested transcript is unresolved", () => {
    useConversationStore.setState({ currentConversationId: null, currentMessages: [] });
    useChatStore.getState().clearMessages();
    const view = mount("c-link");
    expect(view.container.querySelector(".chat-empty-state")).toBeNull();
    expect(screen.getByRole("textbox")).toHaveAttribute("contenteditable", "false");
    act(() => {
      useConversationStore.setState({ currentConversationId: "c-link" });
      useChatStore.getState().addMessage({
        id: "saved",
        role: "user",
        content: "Saved question",
        timestamp: new Date(),
      });
    });
    expect(screen.getByText("Saved question")).toBeInTheDocument();
    expect(view.container.querySelector(".chat-empty-state")).toBeNull();
  });
});

describe("the floating assistant's context submission boundary", () => {
  const page = (): AssistantPageContext => ({
    path: "/tables/orders",
    title: "Orders",
    captured_at: "2026-01-01T00:00:00.000Z",
  });

  it("sends page context with text typed into the normal composer", async () => {
    useAgentSelectionStore.getState().select("agent-1");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const current = page();
    render(
      <QueryClientProvider client={client}>
        <ChatContainer agentFixed pageContext={() => current} />
      </QueryClientProvider>,
    );
    const editor = await screen.findByRole("textbox", { name: "Type a message..." });
    await userEvent.type(editor, "Explain this page");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expect(socket.send).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Explain this page",
          agent_id: "agent-1",
          page_context: current,
        }),
      ),
    );
  });

  it("keeps the submitted page and agent while a draft save holds the question", async () => {
    useAgentSelectionStore.getState().select("agent-1");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let current = page();
    const original = structuredClone(current);
    const at = (holdSending: boolean) => (
      <QueryClientProvider client={client}>
        <ChatContainer
          agentFixed
          holdSending={holdSending}
          pageContext={() => current}
          emptyState={(onPick) => (
            <button type="button" onClick={() => onPick("Explain this page")}>
              pick page
            </button>
          )}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(at(true));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "pick page" }));
    expect(socket.send.mock.calls.filter(([frame]) => frame.message)).toHaveLength(0);
    current = { ...page(), path: "/runs", title: "Runs" };
    act(() => useAgentSelectionStore.getState().select("agent-2"));
    rerender(at(false));
    await act(async () => {});
    expect(socket.send.mock.calls.filter(([frame]) => frame.message)).toHaveLength(0);
    act(() => useAgentSelectionStore.getState().select("agent-1"));

    await waitFor(() =>
      expect(socket.send).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Explain this page",
          agent_id: "agent-1",
          page_context: original,
        }),
      ),
    );
  });

  it("disables submission for an unavailable agent without secretly holding the question", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const at = (sendDisabled: boolean) => (
      <QueryClientProvider client={client}>
        <ChatContainer
          agentFixed
          sendDisabled={sendDisabled}
          pageContext={page}
          emptyState={(onPick) => (
            <button type="button" onClick={() => onPick("Do not defer this")}>
              pick page
            </button>
          )}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(at(true));
    expect(screen.getByRole("textbox")).toHaveAttribute("contenteditable", "false");
    fireEvent.click(screen.getByRole("button", { name: "pick page" }));
    rerender(at(false));
    await act(async () => {});

    expect(socket.send.mock.calls.filter(([frame]) => frame.message)).toHaveLength(0);
  });
});

it("resolves an access request against the requesting agent even after the picker changes", async () => {
  const base = get.getMockImplementation()!;
  get.mockImplementation((url: string) =>
    url === "/agents"
      ? Promise.resolve({
          items: [
            {
              id: "asking-agent",
              slug: "asking-agent",
              name: "Asking agent",
              status: "published",
              local_workspace: true,
            },
            { id: "other-agent", slug: "other-agent", name: "Other agent", status: "published" },
          ],
          total: 2,
        })
      : base(url),
  );
  useAgentSelectionStore.setState({ selectedAgentId: "other-agent" });
  mount();
  await waitFor(() => expect(get).toHaveBeenCalledWith("/agents", expect.anything()));
  receive("computer_access", { reason: "Read files", agent_id: "asking-agent" });
  await waitFor(() =>
    expect(socket.send).toHaveBeenCalledWith({ type: "computer_access_response", granted: false }),
  );
});

it("checks a listed channel participant's view-only share before enabling the composer", async () => {
  const base = get.getMockImplementation()!;
  get.mockImplementation((url: string) =>
    url.startsWith("/conversations?")
      ? Promise.resolve({
          items: [
            {
              id: "channel",
              title: "Channel discussion",
              user_id: "someone-else",
              created_at: "2026-11-09T00:00:00Z",
              is_archived: false,
            },
          ],
          total: 1,
        })
      : url === "/conversations/channel/metadata"
        ? Promise.resolve({ id: "channel", share_permission: "view", user_id: "someone-else" })
        : base(url),
  );
  useConversationStore.getState().setCurrentConversationId("channel");
  mount();
  expect(await screen.findByText("Shared with you as read-only")).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("marks an open shared thread read again when its cached row receives another answer", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useConversationStore.getState().setCurrentConversationId("c-shared-open");
  const key = qk.conversationShares.sharedWithMe(0, 50, "org-1", false);
  client.setQueryData(key, { items: [{ id: "c-shared-open", unread: false }], total: 1 });
  const post = vi.mocked(apiClient.post);
  post.mockResolvedValue(undefined);
  render(
    <QueryClientProvider client={client}>
      <ChatContainer />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(post).toHaveBeenCalledWith("/conversations/c-shared-open/read", {}));
  const before = post.mock.calls.filter(
    ([path]) => path === "/conversations/c-shared-open/read",
  ).length;
  await act(async () => {
    client.setQueryData(key, { items: [{ id: "c-shared-open", unread: true }], total: 1 });
  });
  await waitFor(() =>
    expect(
      post.mock.calls.filter(([path]) => path === "/conversations/c-shared-open/read").length,
    ).toBeGreaterThan(before),
  );
  expect(client.getQueryData(key)).toMatchObject({ items: [{ unread: false }] });
});

it.each(["shared cache", "metadata"])(
  "recovers a legacy shared thread's agent from %s",
  async (source) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) =>
      url.startsWith("/conversations?")
        ? Promise.resolve({
            items: [{ id: "c-legacy", user_id: "someone-else", agents: [] }],
            total: 1,
          })
        : url === "/conversations/c-legacy/metadata"
          ? Promise.resolve({
              id: "c-legacy",
              share_permission: "edit",
              agents: source === "metadata" ? [{ id: "a-fin", name: "Finance" }] : [],
            })
          : base(url),
    );
    if (source === "shared cache") {
      client.setQueryData(qk.conversationShares.sharedWithMe(0, 50, "org-1", false), {
        items: [{ id: "c-legacy", agents: [{ id: "a-fin", name: "Finance" }] }],
        total: 1,
      });
    }
    useAgentSelectionStore.setState({ selectedAgentId: "a-architect" });
    useConversationStore.getState().setCurrentConversationId("c-legacy");
    loadTranscript([
      {
        id: "old",
        conversation_id: "c-legacy",
        role: "assistant",
        content: "Legacy answer",
        created_at: "2025-01-01T00:00:00Z",
      },
    ] as never);
    render(
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>,
    );
    await waitFor(
      () => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-fin"),
      SETTLE,
    );
  },
);

it("keeps the same composer when the first turn learns its new conversation id", async () => {
  const previous = get.getMockImplementation()!;
  get.mockImplementation((url: string) =>
    url === "/conversations/c-created/metadata" ? new Promise<never>(() => {}) : previous(url),
  );
  mount();
  const composer = await screen.findByRole("textbox");
  await userEvent.type(composer, "A follow-up typed before the id arrives");
  receive("conversation_created", { conversation_id: "c-created" });
  expect(screen.queryByText("Checking conversation access…")).toBeNull();
  expect(screen.getByRole("textbox")).toBe(composer);
  expect(messageOf(composer)).toBe("A follow-up typed before the id arrives");
});

it("starts with an empty composer after leaving a first-created chat for New chat", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  mount(undefined, client);
  const conversations = renderHook(() => useConversations(), { wrapper });
  const composer = await screen.findByRole("textbox");
  receive("conversation_created", { conversation_id: "c-created" });
  expect(screen.getByRole("textbox")).toBe(composer);
  await userEvent.type(composer, "Unsaved text in the created chat");

  await act(async () => {
    await conversations.result.current.startNewChat();
  });
  const freshComposer = await screen.findByRole("textbox");
  expect(freshComposer).not.toBe(composer);
  expect(messageOf(freshComposer)).toBe("");
  conversations.unmount();
  client.clear();
});
