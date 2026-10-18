import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { messageOf } from "./composer-editor";
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

describe("the chat container - following the transcript", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("scrolls the transcript's own scroller to a new message, never the page around it", async () => {
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    mount();
    await screen.findByRole("button", { name: "Voice input" });
    scrollTo.mockClear();
    act(() =>
      useChatStore.getState().addMessage({
        id: "m-1",
        role: "user",
        content: "Send the invoice",
        timestamp: new Date(),
      }),
    );
    // `scrollIntoView` scrolls every scrollable ancestor, and the page column
    // around the chat is one: during a call it scrolled the whole chat up and out.
    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    const scroller = scrollTo.mock.contexts.at(-1) as HTMLElement;
    expect(scroller).toHaveClass("overflow-y-auto");
    expect(scroller).toContainElement(await screen.findByText("Send the invoice"));
    expect(scrollTo).toHaveBeenLastCalledWith({ top: scroller.scrollHeight, behavior: "smooth" });
    expect(scrollIntoView).not.toHaveBeenCalled();
    scrollTo.mockRestore();
    scrollIntoView.mockRestore();
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
    const dock = screen.getByRole("textbox").closest(".absolute") as HTMLElement;
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
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-disabled", "true");
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

    expect(await screen.findByText("Hi.")).toBeInTheDocument();
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

    await vi.waitFor(() => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-fin"));

    act(() => useConversationStore.getState().setCurrentConversationId("c-sup"));
    await vi.waitFor(() => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-sup"));
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

    await vi.waitFor(() => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-sup"));
  });

  it("leaves a deliberate switch inside the thread alone", async () => {
    listThreads();
    useConversationStore.getState().setCurrentConversationId("c-fin");
    mount();
    await vi.waitFor(() => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-fin"));

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

    await vi.waitFor(() => expect(reads().length).toBeGreaterThan(before));
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

    expect(
      await screen.findByText("Here is the rollout plan", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
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
