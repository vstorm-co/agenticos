import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatContainer } from "./chat-container";
import { initialCall } from "@/lib/voice/call-reducer";
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

const { get, upload } = vi.hoisted(() => ({
  get: vi.fn(),
  upload: vi.fn(async () => ({ text: "hello" })),
}));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), upload, patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
        level: 0,
        reason: dictation.reason,
        canRetry: dictation.reason !== null,
        retryAfter: null,
        transcript: dictation.inserted ? { id: 1, text: "hello there" } : null,
        upload: dictation.upload,
        stoppedAtLimit: false,
        inserted: dictation.inserted,
      },
      actions: {
        start: vi.fn(),
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
  VoiceGlow: ({
    children,
    active,
    processing,
  }: {
    children: React.ReactNode;
    active?: boolean;
    processing?: boolean;
  }) => (
    <div data-testid="voice-glow" data-active={String(active)} data-processing={String(processing)}>
      {children}
    </div>
  ),
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
    ready: true,
    server_available: true,
    unavailable: null,
    max_seconds: 300,
    provider: "openai",
    format: "wav",
  } as Record<string, unknown>,
}));

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
        : url === "/orgs" && organization.current !== null
          ? Promise.resolve({ items: [organization.current], total: 1 })
          : /^\/agents\/[^/]+\/dictation$/.test(url)
            ? Promise.resolve(readiness.current)
            : Promise.resolve({ items: [], total: 0 }),
  );
  organization.current = null;
  readiness.current = { engine: "server", ready: true, max_seconds: 300, provider: "openai" };
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
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  voiceCall.call = initialCall;
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

describe("the chat container - server dictation", () => {
  beforeEach(() => {
    organization.current = {
      id: "org-1",
      name: "Acme",
      chat_dictation: "server",
      chat_dictation_ready: true,
      dictation_max_seconds: 300,
    };
  });

  it("keeps the glow lit and sweeping while the recording is transcribed", async () => {
    dictation.phase = "transcribing";
    mount();

    // The bar is the composer's own row once the organization's engine is read.
    expect(await screen.findByText("0:42 of audio")).toBeInTheDocument();
    const glow = screen.getByTestId("voice-glow");
    expect(glow).toHaveAttribute("data-active", "true");
    expect(glow).toHaveAttribute("data-processing", "true");
  });

  it("holds the sweep while the bar counts the upload", async () => {
    dictation.phase = "transcribing";
    dictation.upload = 42;
    mount();

    expect(await screen.findByText("Uploading 42%")).toBeInTheDocument();
    const glow = screen.getByTestId("voice-glow");
    expect(glow).toHaveAttribute("data-active", "true");
    expect(glow).toHaveAttribute("data-processing", "false");
  });

  it("shows the words that landed without reading them out a second time", async () => {
    // `ChatInput`'s status region says "Inserted 2 words" already.
    dictation.inserted = true;
    mount();

    expect(await screen.findByTestId("dictation-strip-text")).toHaveTextContent("Inserted 2 words");
    expect(screen.getByTestId("dictation-strip")).toHaveAttribute("aria-live", "off");
  });

  it("puts a failure in the strip under the box, which loses its bottom corners", async () => {
    dictation.phase = "failed";
    dictation.reason = "provider_error";
    mount();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Transcription didn't finish.");
    expect(document.querySelector('[data-tour="chat-composer"]')).toHaveClass("rounded-b-none");
    expect(screen.getByTestId("voice-glow")).toHaveAttribute("data-active", "false");
  });

  it("closes the crossed-out microphone's explanation on Dismiss", async () => {
    mount();
    // Crossed out once the organization is read; before that it is the browser's.
    fireEvent.click(
      await screen.findByRole("button", { name: "Voice input", description: /^Pick an agent/ }),
    );
    const strip = screen.getByTestId("dictation-strip");
    expect(strip).toHaveTextContent("Pick an agent first.");

    fireEvent.click(within(strip).getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(strip).toBeEmptyDOMElement());
  });

  it("does not bring the explanation back by itself once the microphone was usable", async () => {
    mount();
    // Crossed out once the organization is read; before that it is the browser's.
    fireEvent.click(
      await screen.findByRole("button", { name: "Voice input", description: /^Pick an agent/ }),
    );
    const strip = screen.getByTestId("dictation-strip");
    expect(strip).toHaveTextContent("Pick an agent first.");

    act(() => useAgentSelectionStore.setState({ selectedAgentId: "a-1" }));
    // Usable once that agent's readiness answers, which shuts the explanation.
    await waitFor(() => expect(strip).toBeEmptyDOMElement());
    act(() => useAgentSelectionStore.setState({ selectedAgentId: null }));

    expect(strip).toBeEmptyDOMElement();
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

  it("crosses the microphone out for an agent that resolves to nothing usable", async () => {
    readiness.current = { ...readiness.current, ready: false };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    expect(
      await screen.findByRole("button", {
        name: "Voice input",
        description: /^Dictation isn't set up yet\./,
      }),
    ).toBeInTheDocument();
  });

  it("says a key is what is missing when the agent's pair has none", async () => {
    readiness.current = {
      ...readiness.current,
      ready: false,
      server_available: false,
      unavailable: "no_key",
    };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    const mic = await screen.findByRole("button", {
      name: "Voice input",
      description: /^Dictation needs a key\./,
    });
    fireEvent.click(mic);
    expect(screen.getByTestId("dictation-strip")).toHaveTextContent(
      "Dictation needs a key. A speech-to-text model is chosen, but no key for its provider.",
    );
  });

  it("asks no agent about readiness while the organization dictates in the browser", async () => {
    organization.current = { ...organization.current, chat_dictation: "browser" };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    expect(await screen.findByRole("button", { name: "Voice input" })).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/agents/a-1/dictation");
  });

  it("cancels a recording when the organization leaves the server engine mid-sentence", async () => {
    dictation.phase = "recording";
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatContainer />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Stop and transcribe" });
    dictation.cancel.mockClear();

    organization.current = { ...organization.current, chat_dictation: "browser" };
    await act(() => client.invalidateQueries());

    // The bar with its Stop button is gone, so the recording goes with it.
    await waitFor(() => expect(dictation.cancel).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Stop and transcribe" })).not.toBeInTheDocument();
  });

  it("leaves the glow to the open microphone for the browser engine", async () => {
    organization.current = { ...organization.current, chat_dictation: "browser" };
    dictation.phase = "transcribing";
    mount();

    expect(await screen.findByRole("button", { name: "Voice input" })).toBeInTheDocument();
    expect(screen.getByTestId("voice-glow")).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("voice-glow")).toHaveAttribute("data-processing", "false");
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
    minutes_left: 540,
    unavailable_capabilities: [],
  };
  const LIVE_CALL = {
    ...initialCall,
    phase: "live",
    activity: "listening",
    callId: "c1",
    conversationId: "c-a",
    startedAt: Date.now(),
    capSeconds: 600,
    minutesLeft: 540,
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

  it("crosses the button out, with the reason, for an agent that cannot take a call", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      /\/voice$/.test(url)
        ? Promise.resolve({ ...READY_VOICE, available: false, unavailable: "no_voice" })
        : base(url),
    );
    mount();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Start a voice call",
          description: /This agent has no voice set up/,
        }),
      ).toHaveAttribute("aria-disabled", "true"),
    );
  });

  it("turns the composer into the call bar while the call is on, so nothing is sent beside it", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    voiceCall.call = LIVE_CALL;
    const { container } = mount();
    expect(await screen.findByRole("group", { name: "Voice call" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End call" })).toBeInTheDocument();
    // The composer is still mounted, so a draft survives the call - and closed.
    expect(container.querySelector('button[type="submit"]')).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeDisabled();
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
    await waitFor(() => expect(get).toHaveBeenCalledWith("/conversations/c-a/messages"));
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
    await waitFor(() => expect(get).toHaveBeenCalledWith("/conversations/c-new/messages"));
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
    expect(get).not.toHaveBeenCalledWith("/conversations/c-b/messages");
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

  it("offers no call at all where the organization has calls off", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      /\/voice$/.test(url)
        ? Promise.resolve({ ...READY_VOICE, available: false, unavailable: "org_off" })
        : base(url),
    );
    mount();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/agents/a-1/voice"));
    await screen.findByRole("button", { name: "Voice input" });
    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
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
