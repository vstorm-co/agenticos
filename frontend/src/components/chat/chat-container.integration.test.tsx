import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { messageOf } from "./composer-editor";
import { ChatContainer } from "./chat-container";
import { apiClient } from "@/lib/api-client";
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
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
  voiceCall.call = initialCall;
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
      expect(get).toHaveBeenCalledWith("/conversations/c-a/messages?latest=true&limit=101"),
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
      expect(get).toHaveBeenCalledWith("/conversations/c-new/messages?latest=true&limit=101"),
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
    expect(get).not.toHaveBeenCalledWith("/conversations/c-b/messages?latest=true&limit=101");
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
    const dock = screen.getByRole("textbox").closest(".absolute") as HTMLElement;
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
      if (url === `/conversations/${LEFT}/messages?latest=true&limit=101`) {
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
    const reads = () =>
      get.mock.calls.filter(
        ([url]) => url === `/conversations/${LEFT}/messages?latest=true&limit=101`,
      );
    const before = reads().length;

    // The run ends: the next read of the list no longer says it is at work.
    running = null;
    await act(async () => {
      await client.invalidateQueries();
    });

    await vi.waitFor(() => expect(reads().length).toBeGreaterThan(before), SETTLE);
  });

  it("says nothing of an answer left behind while this tab holds the call that is the run", async () => {
    // A call is a run in its conversation, and while the agent thinks the last
    // spoken turn is the caller's: that is not a turn somebody walked away from.
    voiceCall.call = { ...initialCall, phase: "live", callId: "call-1", startedAt: Date.now() };
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

  it("says the answer was lost when its run ended without one, and asks again", async () => {
    // The process running the turn died; the stale-run sweep closed the run and
    // nothing was ever written after the question (#2301).
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
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

  async function openQuestion() {
    useConversationStore.getState().setCurrentConversationId("c-race");
    useConversationStore
      .getState()
      .setCurrentMessages([stored("question", "user", "Initial question")]);
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
    useConversationStore.getState().setCurrentMessages([stored("anchor", "user", "Earlier")]);
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
      useConversationStore.getState().setCurrentMessages([
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
    expect(useChatStore.getState().messages.at(-1)?.content).toContain(
      "Could not persist this answer",
    );
    expect(screen.getByText(/Could not persist this answer/)).toBeVisible();
  });
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
  useConversationStore.getState().setCurrentMessages([current], null, true);
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
