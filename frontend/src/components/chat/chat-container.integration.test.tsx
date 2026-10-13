import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
        cancel: vi.fn(),
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

/** The active organization, with server dictation set up unless told otherwise. */
const organization = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

/** What `GET /agents/{id}/dictation` answers for every agent. */
const readiness = vi.hoisted(() => ({
  current: {
    engine: "server",
    ready: true,
    server_available: true,
    max_seconds: 300,
    provider: "openai",
    format: "webm",
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
    // An agent overriding to Mistral in an organization on OpenAI records WAV,
    // which Mistral takes, rather than the WebM it refuses - and the backend's
    // catalog says so, not a list of providers kept here.
    organization.current = { ...organization.current, speech_to_text_provider: "openai" };
    readiness.current = { ...readiness.current, provider: "mistral", format: "wav" };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    await waitFor(() => expect(dictation.format).toBe("wav"));
    expect(get).toHaveBeenCalledWith("/agents/a-1/dictation");
  });

  it("records WebM and has nowhere to send before an agent is chosen", () => {
    organization.current = null;
    mount();

    expect(dictation.format).toBe("webm");
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

  it("asks no agent about readiness while the organization dictates in the browser", async () => {
    organization.current = { ...organization.current, chat_dictation: "browser" };
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    expect(await screen.findByRole("button", { name: "Voice input" })).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/agents/a-1/dictation");
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
