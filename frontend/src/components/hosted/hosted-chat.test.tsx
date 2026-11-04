import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render as renderBare, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HostedChat } from "./hosted-chat";
import type { DictationState } from "@/hooks/use-dictation";
import type { DictationSend } from "@/lib/dictation-api";
import { initialCall, type CallState } from "@/lib/voice/call-reducer";
import type { HostedPageConfig } from "@/types/hosted";
import type { VoiceSavedTurn } from "@/types/voice";

/**
 * The recorder, as a phase each test sets. What is under test here is what the
 * page hands it and draws for a phase; the recording itself is
 * `use-dictation.test.ts`, shared with the console's composer.
 */
const dictation = vi.hoisted(() => ({
  state: null as Partial<DictationState> | null,
  options: null as { send: DictationSend | null; maxSeconds: number; format: string } | null,
  actions: {
    start: vi.fn(),
    stop: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
    dismiss: vi.fn(),
    dismissInserted: vi.fn(),
  },
}));
vi.mock("@/hooks/use-dictation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-dictation")>()),
  useDictation: (options: { send: DictationSend | null; maxSeconds: number; format: string }) => {
    dictation.options = options;
    return {
      state: {
        phase: "idle",
        elapsed: 3,
        remaining: null,
        silent: false,
        meter: { read: () => 0, subscribe: () => () => {} },
        reason: null,
        canRetry: false,
        retryAfter: null,
        transcript: null,
        upload: null,
        stoppedAtLimit: false,
        inserted: false,
        ...dictation.state,
      },
      actions: dictation.actions,
    };
  },
}));

/**
 * The voice call, as a session each test sets (#54). What is under test is what
 * the page does with a call - where the bar goes, what the button starts, how a
 * saved turn reaches the thread - not the socket (`use-voice-session.test.tsx`,
 * which also hangs the call up on unmount and `pagehide`).
 */
const voiceCall = vi.hoisted(() => ({
  call: null as unknown,
  start: vi.fn(),
  end: vi.fn(),
  dismiss: vi.fn(),
  decide: vi.fn(),
  options: {} as {
    onTurnSaved?: (message: VoiceSavedTurn) => void;
    onConversation?: (id: string) => void;
  },
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
      decide: voiceCall.decide,
      dismissUnavailable: vi.fn(),
      dismiss: voiceCall.dismiss,
    };
  },
}));

// The real renderer is loaded with `next/dynamic` and `ssr: false`, so under
// jsdom it renders its own placeholder and every assertion on an answer's words
// would be asserting on a non-breaking space. What it renders is tested where it
// lives; what matters here is that the answer reaches it at all.
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <span>{content}</span>,
}));

/**
 * The page renders web chat's own turn components, and two of their renderers reach
 * for a query client - the workspace card, to turn a file the agent wrote into one
 * somebody can open. In the app there is one: `src/app/[locale]/layout.tsx` wraps
 * every locale route, this one included. Here there is not, so the test supplies it
 * rather than the component defending against its absence.
 */
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // A wrapper rather than a parent, so `rerender` keeps the page mounted.
  return renderBare(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

/**
 * The page somebody reaches by a link, signed into nothing.
 *
 * What is worth asserting here is what the surface *promises*: that a bookmarked
 * link comes back to its thread, that the welcome message is shown and never
 * spoken, that only URL-safe variables leave the address bar, and that a rate
 * limit reads as "try again" while a refusal reads as "not available". Everything
 * else - the budget, the approval gate, the tenant - is the runner's and is
 * tested where it lives.
 */

class FakeSocket {
  static last: FakeSocket | null = null;
  static readonly OPEN = 1;
  readyState = 1;
  sent: string[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    FakeSocket.last = this;
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  deliver(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

function config(overrides: Partial<HostedPageConfig> = {}): HostedPageConfig {
  return {
    public_key: "pk_abc",
    title: "Refunds",
    welcome: "",
    accent: "#4f46e5",
    logo_url: null,
    agent_name: "Refund helper",
    variables: [],
    dictation: "off",
    dictation_max_seconds: 300,
    dictation_format: "webm",
    voice_conversation: false,
    voice_transport: null,
    allow_new_conversation: true,
    allow_files: false,
    ...overrides,
  };
}

beforeEach(() => {
  // A stubbed recogniser must not outlive its test: the assertion that a browser
  // without one renders no microphone would pass or fail on ordering.
  vi.unstubAllGlobals();
  window.localStorage.clear();
  dictation.state = null;
  dictation.options = null;
  for (const action of Object.values(dictation.actions)) action.mockReset();
  voiceCall.call = initialCall;
  voiceCall.options = {};
  for (const action of [voiceCall.start, voiceCall.end, voiceCall.dismiss, voiceCall.decide]) {
    action.mockReset();
  }
  FakeSocket.last = null;
  vi.stubGlobal("WebSocket", FakeSocket);
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function socket(): FakeSocket {
  if (FakeSocket.last === null) throw new Error("no socket opened");
  return FakeSocket.last;
}

describe("the hosted page", () => {
  it("names itself with the title the operator chose", () => {
    render(<HostedChat config={config()} />);

    expect(screen.getByRole("heading", { name: "Refunds" })).toBeInTheDocument();
  });

  it("shows the welcome message before the first question, as Markdown", () => {
    // The operator writes it in a Markdown editor, so printing the asterisks would
    // be the one place on this page that shows source instead of text. The renderer
    // is mocked to echo, so what is asserted is that it went through it.
    render(<HostedChat config={config({ welcome: "**Ask** about a refund." })} />);

    expect(screen.getByText("**Ask** about a refund.")).toBeInTheDocument();
  });

  it("never sends the welcome message to the agent", async () => {
    // A greeting in the model's history is a turn the agent thinks it took.
    render(<HostedChat config={config({ welcome: "Ask about a refund." })} />);

    await userEvent.type(screen.getByRole("textbox"), "where is my money");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(socket().sent).toHaveLength(1);
    expect(socket().sent[0]).not.toContain("Ask about a refund");
  });

  it("mints a visitor key and keeps it, so a bookmarked link is the same visitor", () => {
    render(<HostedChat config={config()} />);
    const first = socket().url;

    render(<HostedChat config={config()} />);

    expect(socket().url).toBe(first);
    expect(first).toMatch(/\?visitor=[0-9a-f]{32}$/);
  });

  it("opens with a fresh key when localStorage is blocked rather than crashing", () => {
    // "Block all cookies" makes even reading window.localStorage throw. The page
    // must open on an in-memory key, not hand the visitor the error boundary.
    const denied = () => {
      throw new DOMException("denied", "SecurityError");
    };
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(denied);
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(denied);
    try {
      render(<HostedChat config={config()} />);

      expect(socket().url).toMatch(/\?visitor=[0-9a-f]{32}$/);
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("paints the send button with the operator's accent", () => {
    // The colour is configured, stored and served; before this it reached the
    // DOM nowhere, so the picker was a no-op.
    render(<HostedChat config={config({ accent: "#ff0000" })} />);

    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toHaveStyle({ backgroundColor: "var(--hosted-accent)" });
    expect(send.closest("[style*='--hosted-accent']")).not.toBeNull();
  });

  it("keeps a separate key per public key", () => {
    // Two hosted pages are two conversations with two agents; one shared id
    // would put them in the same thread on the server.
    render(<HostedChat config={config({ public_key: "pk_one" })} />);
    const first = socket().url;

    render(<HostedChat config={config({ public_key: "pk_two" })} />);

    expect(socket().url).not.toBe(first);
  });

  it("shows the thread a returning visitor left open", () => {
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "history",
        data: {
          messages: [
            { role: "user", text: "do you ship to Poland?" },
            { role: "assistant", text: "we do" },
          ],
        },
      }),
    );

    expect(screen.getByText("do you ship to Poland?")).toBeInTheDocument();
    expect(screen.getByText("we do")).toBeInTheDocument();
  });

  it("forwards a URL-safe variable and drops one nobody marked", async () => {
    // Both directions in one, because the pair is the rule: the server drops the
    // undeclared one regardless, so this keeps the page from sending a value that
    // would only be thrown away - and proves the declared one does arrive.
    window.history.replaceState({}, "", "/e/pk_abc?var_plan=pro&var_user_tier=premium");
    render(<HostedChat config={config({ variables: ["plan"] })} />);

    await userEvent.type(screen.getByRole("textbox"), "hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    const frame = JSON.parse(socket().sent[0]!);
    expect(frame.context).toEqual({ plan: "pro" });
  });

  it("shows the answer and stops saying it is working", async () => {
    render(<HostedChat config={config()} />);

    await userEvent.type(screen.getByRole("textbox"), "hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    act(() => socket().deliver({ type: "model_request_start", data: {} }));
    expect(screen.getByText("Working on it…")).toBeInTheDocument();

    act(() => socket().deliver({ type: "text_delta", data: { content: "30 " } }));
    act(() => socket().deliver({ type: "text_delta", data: { content: "days" } }));
    act(() => socket().deliver({ type: "complete", data: {} }));

    // The streamed answer is paced onto the page over a few frames rather than
    // painted in bursts, so it is awaited rather than read synchronously.
    expect(await screen.findByText("30 days")).toBeInTheDocument();
    expect(screen.queryByText("Working on it…")).toBeNull();
  });

  it("tells a rate-limited visitor to come back rather than that it is broken", () => {
    // 4029 and 4003 mean opposite things to somebody reading the page: one is
    // "wait", the other is "this is not for you".
    render(<HostedChat config={config()} />);

    act(() => socket().onclose?.({ code: 4029 }));

    expect(screen.getByText(/Too many connections/)).toBeInTheDocument();
  });

  it("says a refused page is unavailable, and nothing about why", () => {
    render(<HostedChat config={config()} />);

    act(() => socket().onclose?.({ code: 4003 }));

    expect(screen.getByText("This assistant is not available right now.")).toBeInTheDocument();
  });

  it("stops offering the composer once the socket is closed", () => {
    render(<HostedChat config={config()} />);

    act(() => socket().onclose?.({ code: 4003 }));

    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("says the connection was lost on an abnormal close, and disables the composer", async () => {
    // A network blip or a server restart carries neither 4029 nor 4003. The
    // composer must not stay enabled to swallow a send silently.
    render(<HostedChat config={config()} />);

    act(() => socket().onclose?.({ code: 1006 }));

    expect(screen.getByText("The connection was lost.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
    // Reconnect reopens the socket on the same key rather than starting a fresh
    // thread, so the composer comes back.
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(screen.getByRole("textbox")).toBeEnabled();
  });

  it.each([1006, 1011, 4029, 4003])(
    "settles the turn a close of %i interrupted, rather than leaving it running",
    async (code) => {
      // `finished()` is what ends a turn, and `error` and `complete` reach it
      // through `fold`. A close reached nothing, so the caret kept pulsing and a
      // tool step stayed running under a notice saying the connection was gone -
      // exactly what 81dac010 fixed for an `error` frame, one path over.
      render(<HostedChat config={config()} />);
      await userEvent.type(screen.getByRole("textbox"), "hello");
      await userEvent.click(screen.getByRole("button", { name: "Send" }));
      act(() =>
        socket().deliver({
          type: "tool_call",
          data: { tool_call_id: "c1", tool_name: "search_knowledge" },
        }),
      );
      act(() => socket().deliver({ type: "text_delta", data: { content: "Checking" } }));

      act(() => socket().onclose?.({ code }));

      expect(screen.queryByText("Working on it…")).toBeNull();
      expect(document.querySelector(".animate-pulse")).toBeNull();
      expect(screen.queryByText(/Searching/)).toBeNull();
    },
  );
});

describe("what the operator lets the page offer", () => {
  it("starts a fresh thread on a new key, and forgets what was on screen", async () => {
    // The server maps a continuity key to a conversation, so a new key is a new
    // thread. The old one is not deleted - it stops being the one this browser
    // resumes.
    render(<HostedChat config={config()} />);
    FakeSocket.last!.deliver({
      type: "history",
      data: { messages: [{ role: "user", text: "earlier" }] },
    });

    const before = window.localStorage.getItem("agenticos:visitor:pk_abc");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(window.localStorage.getItem("agenticos:visitor:pk_abc")).not.toBe(before);
    expect(screen.queryByText("earlier")).toBeNull();
  });

  it("offers no way to start one when the operator did not allow it", () => {
    render(<HostedChat config={config({ allow_new_conversation: false })} />);

    expect(screen.queryByRole("button", { name: "New chat" })).toBeNull();
  });

  it("offers no microphone unless the operator turned it on", () => {
    render(<HostedChat config={config({ dictation: "off" })} />);

    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
  });

  it("offers no microphone in a browser that has none, even when allowed", () => {
    // A control that cannot work is not rendered - the same rule the dashboard
    // applies to a permission somebody lacks.
    render(<HostedChat config={config({ dictation: "browser" })} />);

    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
  });

  it("dictates into the draft rather than sending anything anywhere", async () => {
    // The browser's own recogniser: the transcript lands in the box exactly as
    // if it had been typed, and no audio reaches this deployment.
    const recognition = {
      continuous: false,
      interimResults: false,
      lang: "",
      onresult: null as ((event: unknown) => void) | null,
      onend: null as (() => void) | null,
      onerror: null as (() => void) | null,
      start: vi.fn(),
      stop: vi.fn(),
    };
    // A `function` expression, not an arrow: the component calls this with
    // `new`, and an arrow is not a constructor.
    vi.stubGlobal(
      "SpeechRecognition",
      vi.fn(function () {
        return recognition;
      }),
    );

    render(<HostedChat config={config({ dictation: "browser" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Dictate" }));

    expect(recognition.start).toHaveBeenCalled();

    recognition.onresult?.({
      resultIndex: 0,
      results: [Object.assign([{ transcript: "where is my order" }], { isFinal: true })],
    });

    expect(await screen.findByDisplayValue("where is my order")).toBeInTheDocument();
    expect(FakeSocket.last!.sent).toEqual([]);
  });
});

describe("server dictation on the page", () => {
  const server = (overrides: Partial<HostedPageConfig> = {}) =>
    config({
      dictation: "server",
      dictation_max_seconds: 90,
      dictation_format: "wav",
      ...overrides,
    });

  it("records in the format and to the limit the backend sent", async () => {
    render(<HostedChat config={server()} />);
    await userEvent.click(screen.getByRole("button", { name: "Dictate" }));

    expect(dictation.actions.start).toHaveBeenCalledOnce();
    expect(dictation.options).toMatchObject({ maxSeconds: 90, format: "wav" });
  });

  it("has nowhere to send a recording on a page that is not on server", () => {
    render(<HostedChat config={config({ dictation: "browser" })} />);

    expect(dictation.options!.send).toBeNull();
  });

  it("posts a recording to its own route with the visitor's key, never in the URL", async () => {
    // By XMLHttpRequest, the one way to hear how much of it has gone up.
    const sent: { url: string; headers: Record<string, string> }[] = [];
    class Xhr {
      upload = { onprogress: null, onload: null as (() => void) | null };
      onload: (() => void) | null = null;
      status = 200;
      statusText = "OK";
      responseText = JSON.stringify({ text: "where is my order" });
      private request = { url: "", headers: {} as Record<string, string> };
      open(_method: string, url: string) {
        this.request.url = url;
      }
      setRequestHeader(name: string, value: string) {
        this.request.headers[name] = value;
      }
      getAllResponseHeaders() {
        return "";
      }
      send() {
        sent.push(this.request);
        this.upload.onload?.();
        this.onload?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", Xhr);
    const progress = vi.fn();
    render(<HostedChat config={server()} />);

    const text = await dictation.options!.send!(
      new Blob(["a"], { type: "audio/wav" }),
      2,
      new AbortController().signal,
      progress,
    );

    expect(text).toBe("where is my order");
    expect(progress).toHaveBeenCalledWith(1);
    const [{ url, headers }] = sent as [(typeof sent)[number]];
    expect(url).toMatch(/\/api\/v1\/embed\/pk_abc\/dictation$/);
    const visitor = window.localStorage.getItem("agenticos:visitor:pk_abc");
    expect(headers["x-visitor-key"]).toBe(visitor);
  });

  it("swaps the box for the recording bar while a recording is open, and Esc cancels", async () => {
    dictation.state = { phase: "recording" };
    render(<HostedChat config={server()} />);

    expect(screen.queryByRole("textbox")).toBeNull();
    const stop = screen.getByRole("button", { name: "Stop and transcribe" });
    await userEvent.type(stop, "{Shift}");
    expect(dictation.actions.cancel).not.toHaveBeenCalled();
    await userEvent.type(stop, "{Escape}");

    expect(dictation.actions.cancel).toHaveBeenCalledOnce();
  });

  it("puts the transcript in the box and sends nothing", async () => {
    const view = render(<HostedChat config={server()} />);
    await userEvent.type(screen.getByRole("textbox"), "Hello");

    dictation.state = { transcript: { id: 1, text: "where is my order" } };
    view.rerender(<HostedChat config={server()} />);

    expect(await screen.findByDisplayValue("Hello where is my order")).toBeInTheDocument();
    expect(FakeSocket.last!.sent).toEqual([]);
  });

  it("says the words landed, aloud as well, and lets the next key put it away", async () => {
    // The page has no status region of its own: the strip is the announcement.
    dictation.state = { inserted: true, transcript: { id: 1, text: "where is my order" } };
    render(<HostedChat config={server()} />);

    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent("Inserted 4 words");
    expect(screen.getByTestId("dictation-strip")).toHaveAttribute("aria-live", "polite");
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "{Shift}");
    expect(dictation.actions.dismissInserted).not.toHaveBeenCalled();
    await userEvent.type(box, "?");
    expect(dictation.actions.dismissInserted).toHaveBeenCalled();
  });

  it("leaves the draft's keys alone when nothing was just inserted", async () => {
    render(<HostedChat config={server()} />);

    await userEvent.type(screen.getByRole("textbox"), "hi");

    expect(dictation.actions.dismissInserted).not.toHaveBeenCalled();
  });

  it("counts the upload in the bar while it is going up", () => {
    dictation.state = { phase: "transcribing", upload: 42 };
    render(<HostedChat config={server()} />);

    expect(screen.getByText("Uploading 42%")).toBeInTheDocument();
  });

  it("says the recording stopped at the page's limit while it is transcribed", () => {
    dictation.state = { phase: "transcribing", stoppedAtLimit: true };
    render(<HostedChat config={server()} />);

    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent(
      "Stopped at the 1:30 limit. Transcribing everything up to here.",
    );
  });

  it("tells a visitor what to do when it is not set up, naming no admin", () => {
    dictation.state = { phase: "failed", reason: "not_configured" };
    render(<HostedChat config={server()} />);

    const strip = screen.getByTestId("dictation-strip-text");
    expect(strip).toHaveTextContent("Voice input isn't available right now.");
    expect(strip).not.toHaveTextContent(/admin|organization/i);
  });
});

describe("what the page does with the frames it is sent", () => {
  it("shows the agent's work as a line, named the way the dashboard names it", () => {
    // Through `src/lib/tool-catalog.ts`, not a second table of tool names: the
    // last time that knowledge was duplicated, two renamed tools rendered as raw
    // JSON for five weeks with a green suite (#144).
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "search_documents" },
      }),
    );

    expect(screen.getByText("Searching the documents")).toBeInTheDocument();
  });

  it("opens a step into what came back, when the server sent it", async () => {
    // A name the catalog has never heard of - an MCP tool, or one a binding renamed
    // - which is the generic renderer and the one that shows a result verbatim.
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "post_invoice" },
      }),
    );
    act(() =>
      socket().deliver({ type: "tool_result", data: { tool_call_id: "c1", content: "30 days" } }),
    );

    // Behind the step rather than under it, which is what web chat does: a
    // transcript that opened every finished call is a wall of results.
    expect(screen.queryByText("30 days")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Post Invoice/ }));

    expect(screen.getByText("30 days")).toBeInTheDocument();
  });

  it("shows a generated image through the page's own link, not the console's", () => {
    // The console's address forwards a session, and a visitor has none - so the
    // card asked for a file it could not open (#2309). The socket signs a link for
    // this visitor's file, and the card reads it through this page's key.
    const token = `1792689903.${"a".repeat(64)}`;
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "generate_image" },
      }),
    );
    act(() =>
      socket().deliver({
        type: "tool_result",
        data: {
          tool_call_id: "c1",
          content: JSON.stringify({
            kind: "generated_image",
            filename: "abc_image.png",
            prompt: "a lighthouse",
            token,
          }),
        },
      }),
    );

    expect(screen.getByRole("img", { name: "a lighthouse" })).toHaveAttribute(
      "src",
      `/api/embed/pk_abc/generated/abc_image.png?token=${token}`,
    );
  });

  it("renders the reasoning it was sent, and nothing where it was not", () => {
    // The page has no branch that hides it: a page whose operator left
    // `show_thinking` off never receives the frame, which is what makes the
    // setting mean something on a surface with devtools.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "thinking_delta", data: { content: "Checking policy." } }));

    expect(screen.getByText("Checking policy.")).toBeInTheDocument();
  });

  it("keeps one bubble for a turn rather than one per frame", async () => {
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Thirty " } }));
    act(() => socket().deliver({ type: "text_delta", data: { content: "days." } }));
    // Ended, so the text is whole: mid-turn each word is its own span, and the
    // last one waits in case it is still arriving.
    act(() => socket().deliver({ type: "complete", data: {} }));

    expect(await screen.findByText("Thirty days.")).toBeInTheDocument();
  });

  it("starts a new bubble once a turn is over", async () => {
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "First." } }));
    act(() => socket().deliver({ type: "complete", data: {} }));
    act(() => socket().deliver({ type: "text_delta", data: { content: "Second." } }));
    act(() => socket().deliver({ type: "complete", data: {} }));

    // Found rather than got: a short answer flows in, and its words keep their
    // fade-in spans until the last one has surfaced.
    expect(await screen.findByText("First.")).toBeInTheDocument();
    expect(await screen.findByText("Second.")).toBeInTheDocument();
  });

  it("settles on what the run ended with", async () => {
    // A provider that streams no deltas leaves `final_result` as the only copy of
    // the answer, so it is assigned rather than appended.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "final_result", data: { output: "Thirty days." } }));
    act(() => socket().deliver({ type: "complete", data: {} }));

    expect(await screen.findByText("Thirty days.")).toBeInTheDocument();
  });

  it("replaces an empty turn with the reason it produced nothing", () => {
    // A run parked on an approval streams a `final_result` with no output. Two
    // bubbles - one blank, one explaining - is worse than one.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "model_request_start", data: {} }));
    act(() => socket().deliver({ type: "final_result", data: { output: "" } }));
    act(() =>
      socket().deliver({
        type: "error",
        data: { message: "That needs somebody to approve it before it can run." },
      }),
    );
    act(() => socket().deliver({ type: "complete", data: {} }));

    expect(
      screen.getByText("That needs somebody to approve it before it can run."),
    ).toBeInTheDocument();
  });

  it("stops a turn's spinner when an error arrives with no trailing complete", () => {
    // The route's own failure path fails a turn without a `complete`. A turn that
    // had streamed a running tool call must not keep animating under the refusal
    // - the error finishes it the way complete would.
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "search_documents" },
      }),
    );
    act(() => socket().deliver({ type: "error", data: { message: "Something went wrong." } }));

    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
    // The step is present but settled, not spinning: no progressbar is left behind.
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("ignores a frame it has never heard of", () => {
    // A page cached in somebody's browser may be older than this server. Closing
    // the thread over an unknown frame would take the conversation with it.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "delegation_started", data: { name: "researcher" } }));

    expect(screen.getByRole("textbox")).toBeEnabled();
  });
});

describe("attaching a file", () => {
  it("offers no picker unless the operator allowed one", () => {
    render(<HostedChat config={config()} />);

    expect(screen.queryByRole("button", { name: "Attach a file" })).toBeNull();
  });

  it("stores the file and names it on the next message", async () => {
    // The id is what the turn carries, so the file is stored first and the
    // message names it - a file attached and then thought better of must not
    // become a turn of its own.
    const fetched = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "f-1", filename: "invoice.pdf" }),
    });
    vi.stubGlobal("fetch", fetched);
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<HostedChat config={config({ allow_files: true })} />);

    const file = new File(["x"], "invoice.pdf", { type: "application/pdf" });
    await userEvent.upload(document.querySelector('input[type="file"]')!, file);

    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    // The visitor key travels with it: the limit is counted per visitor and per
    // page, so an upload with no key is one the server cannot bound. It rides a
    // header, not the query string - it is a bearer credential and a query lands
    // in access logs.
    expect(fetched.mock.calls[0]![0]).toMatch(/\/files$/);
    const sentHeaders = fetched.mock.calls[0]![1]!.headers as Record<string, string>;
    expect(sentHeaders["X-Visitor-Key"]).toMatch(/^[0-9a-f]{32}$/);

    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(JSON.parse(socket().sent[0]!).file_ids).toEqual(["f-1"]);
  });

  it("says so when a file was refused rather than doing nothing", async () => {
    // A picker that appears to do nothing is worse than a sentence: the refusal
    // is about the file - too large, a type nothing can read - and is fixable.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<HostedChat config={config({ allow_files: true })} />);

    await userEvent.upload(
      document.querySelector('input[type="file"]')!,
      new File(["x"], "huge.zip", { type: "application/zip" }),
    );

    expect(await screen.findByText("That file could not be attached.")).toBeInTheDocument();
  });

  it("lets a visitor change their mind before sending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ id: "f-1", filename: "invoice.pdf" }),
      }),
    );
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<HostedChat config={config({ allow_files: true })} />);
    await userEvent.upload(
      document.querySelector('input[type="file"]')!,
      new File(["x"], "invoice.pdf", { type: "application/pdf" }),
    );
    await screen.findByText("invoice.pdf");

    await userEvent.click(screen.getByRole("button", { name: "Remove invoice.pdf" }));

    expect(screen.queryByText("invoice.pdf")).toBeNull();
  });

  it("sends a file with no words at all", async () => {
    // Somebody drops a screenshot and asks nothing. The server writes the turn
    // anyway, because the row is what the file hangs off.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({ ok: true, json: async () => ({ id: "f-1", filename: "shot.png" }) }),
    );
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<HostedChat config={config({ allow_files: true })} />);
    await userEvent.upload(
      document.querySelector('input[type="file"]')!,
      new File(["x"], "shot.png", { type: "image/png" }),
    );
    await screen.findByText("shot.png");

    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(JSON.parse(socket().sent[0]!)).toMatchObject({ text: "", file_ids: ["f-1"] });
  });
});

describe("a turn laid out the way web chat lays one out", () => {
  it("keeps a turn's words and its work in the order they arrived", async () => {
    // The reason the page holds `MessagePart[]` rather than a string and a list of
    // steps beside it: an agent that speaks, works, then speaks again is three
    // things in that sequence. The old shape rendered the whole answer above all of
    // the work whatever actually happened.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Let me look." } }));
    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "post_invoice" },
      }),
    );
    act(() => socket().deliver({ type: "text_delta", data: { content: "Thirty days." } }));
    act(() => socket().deliver({ type: "complete", data: {} }));

    // Finished, the work folds into one line above the answer; opened, it is in
    // the order it happened.
    fireEvent.click(await screen.findByRole("button", { name: "Worked · 1 step" }));
    const said = await screen.findByText("Let me look.");
    const step = screen.getByRole("button", { name: /Post Invoice/ });
    const answered = await screen.findByText("Thirty days.");
    expect(said.compareDocumentPosition(step)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(step.compareDocumentPosition(answered)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("stops a step animating once the turn is over", () => {
    // A call with no result when `complete` arrives never got one - the run broke,
    // or parked on it. A spinner under a turn that has ended is a promise nothing is
    // going to keep, which is why web chat calls that state `unfinished`.
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "post_invoice" },
      }),
    );
    expect(screen.getByText("Running")).toBeInTheDocument();

    act(() => socket().deliver({ type: "complete", data: {} }));

    expect(screen.queryByText("Running")).toBeNull();
  });

  it("renders the answer as Markdown and the question as plain text", () => {
    // The same split web chat makes: an agent told to answer in Markdown is
    // answering in it, and what a visitor typed is not a document.
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "history",
        data: {
          messages: [
            { role: "user", text: "**not bold**" },
            { role: "assistant", text: "# A heading" },
          ],
        },
      }),
    );

    // The renderer is mocked to echo, so what is asserted is which side reached it.
    expect(screen.getByText("**not bold**")).toBeInTheDocument();
    expect(screen.getByText("# A heading")).toBeInTheDocument();
  });
});

describe("the chrome around a turn", () => {
  it("names the agent above its answer", () => {
    // Web chat draws this line, and without it an answer has no author on a page
    // whose whole subject is one agent. The *version* stays out: what a stored spec
    // is called is an internal fact.
    render(<HostedChat config={config({ agent_name: "JARVIS" })} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Hi." } }));

    expect(screen.getByText("JARVIS")).toBeInTheDocument();
  });

  it("falls back to the agent's initial where there is no picture", () => {
    // What `AgentAvatar` does in the dashboard. A generic robot glyph was the one
    // thing on this page that looked like a different product.
    render(<HostedChat config={config({ agent_name: "jarvis", logo_url: null })} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Hi." } }));

    expect(screen.getByText("J")).toBeInTheDocument();
  });

  it("prints the time a replayed turn was written, not the time it was read", () => {
    // The `history` frame carries `at` for this: a bookmarked link comes back with
    // the times still under its turns, which is the visit continuity exists for.
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "history",
        data: {
          messages: [{ role: "user", text: "earlier", at: "2026-08-12T17:46:00+00:00" }],
        },
      }),
    );

    const printed = new Date("2026-08-12T17:46:00+00:00").toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(screen.getByText(printed)).toBeInTheDocument();
  });

  it("prints no time while the turn is still being written", () => {
    // A time under a turn that has not finished is a time that is about to be wrong.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Thinking" } }));

    expect(screen.queryByText(/^\d{1,2}:\d{2}/)).toBeNull();
  });
});

describe("a voice call on the page (#54)", () => {
  const voice = (overrides: Partial<HostedPageConfig> = {}) =>
    config({ voice_conversation: true, voice_transport: "webrtc", ...overrides });
  const LIVE: CallState = {
    ...initialCall,
    phase: "live",
    activity: "listening",
    callId: "c1",
    conversationId: "conv-1",
    transport: "webrtc",
    startedAt: Date.now(),
    capSeconds: 600,
  };
  const saved = (overrides: Partial<VoiceSavedTurn> = {}): VoiceSavedTurn => ({
    id: "m1",
    role: "user",
    content: "Where is my refund?",
    interrupted: false,
    turn_id: "c1:1:user",
    ...overrides,
  });

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  it("offers a call on a page whose config says so, and starts it as the page's visitor", async () => {
    render(<HostedChat config={voice()} />);
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    // The same visitor the thread belongs to, so the call lands in that thread.
    const visitor = new URL(socket().url).searchParams.get("visitor");
    expect(voiceCall.start).toHaveBeenCalledWith({
      kind: "embed",
      publicKey: "pk_abc",
      visitorKey: visitor,
      token: null,
      transport: "webrtc",
      context: {},
    });
  });

  it("starts the call as the socket's visitor when localStorage is blocked", async () => {
    // With nowhere to store the key, the page keeps one for its lifetime: a second
    // key for the call would put it in a thread the page's socket is not in.
    const denied = () => {
      throw new DOMException("denied", "SecurityError");
    };
    // On the instance: the suite's storage is a stand-in, not a `Storage`.
    const getItem = vi.spyOn(window.localStorage, "getItem").mockImplementation(denied);
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(denied);
    try {
      render(<HostedChat config={voice({ public_key: "pk_blocked" })} />);
      await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

      const visitor = new URL(socket().url).searchParams.get("visitor");
      expect(getItem).toHaveBeenCalled();
      expect(voiceCall.start).toHaveBeenCalledWith(
        expect.objectContaining({ visitorKey: visitor }),
      );
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("starts the call as the socket's visitor when storage reads but cannot keep a key", async () => {
    // Full storage: nothing stored to read, and the minted key not kept either.
    const getItem = vi.spyOn(window.localStorage, "getItem").mockReturnValue(null);
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    try {
      render(<HostedChat config={voice({ public_key: "pk_full" })} />);
      await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

      const visitor = new URL(socket().url).searchParams.get("visitor");
      expect(voiceCall.start).toHaveBeenCalledWith(
        expect.objectContaining({ visitorKey: visitor }),
      );
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("briefs the call with the page's supplied variables, as a typed message is", async () => {
    window.history.replaceState({}, "", "/e/pk_abc?var_order=123&var_secret=x");
    render(<HostedChat config={voice({ variables: ["order"] })} />);
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    expect(voiceCall.start).toHaveBeenCalledWith(
      expect.objectContaining({ context: { order: "123" } }),
    );
  });

  it("starts a relayed call as a relayed one", async () => {
    render(<HostedChat config={voice({ voice_transport: "relay" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    expect(voiceCall.start).toHaveBeenCalledWith(expect.objectContaining({ transport: "relay" }));
  });

  it("offers no call button when the config does not", () => {
    render(<HostedChat config={config({ voice_conversation: false, voice_transport: null })} />);

    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
  });

  it("offers no call button when the config names no way to carry it", () => {
    render(<HostedChat config={voice({ voice_transport: null })} />);

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
  });

  it("offers no call while the page's socket is closed", () => {
    render(<HostedChat config={voice()} />);
    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeEnabled();

    act(() => socket().onclose?.({ code: 1006 }));

    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeDisabled();
  });

  it("offers no call while the agent is thinking", () => {
    render(<HostedChat config={voice()} />);

    act(() => socket().deliver({ type: "model_request_start", data: {} }));

    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeDisabled();
  });

  it("offers no call while an answer is still being written", () => {
    // Starting a call reopens the page's socket; mid-answer, that would cut the answer off.
    render(<HostedChat config={voice()} />);
    act(() => socket().deliver({ type: "text_delta", data: { content: "Let me look" } }));

    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeDisabled();
  });

  it("turns the composer into the call bar while the call is on", () => {
    voiceCall.call = LIVE;
    render(<HostedChat config={voice({ dictation: "server" })} />);

    expect(screen.getByRole("group", { name: "Voice call" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End call" })).toBeInTheDocument();
    // Still mounted, so a draft survives the call - but out of reach, and with
    // it the microphone: a call and a dictation never run at once.
    expect(screen.getByRole("textbox", { hidden: true })).not.toBeVisible();
    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
  });

  it("ends the call from the bar", async () => {
    voiceCall.call = LIVE;
    render(<HostedChat config={voice()} />);
    await userEvent.click(screen.getByRole("button", { name: "End call" }));

    expect(voiceCall.end).toHaveBeenCalled();
  });

  it("stops the browser's dictation when a call starts", async () => {
    const recognition = {
      continuous: false,
      interimResults: false,
      lang: "",
      onresult: null,
      onend: null,
      onerror: null,
      start: vi.fn(),
      stop: vi.fn(),
    };
    vi.stubGlobal(
      "SpeechRecognition",
      vi.fn(function () {
        return recognition;
      }),
    );
    const view = render(<HostedChat config={voice({ dictation: "browser" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Dictate" }));
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));
    expect(voiceCall.start).toHaveBeenCalled();

    voiceCall.call = { ...initialCall, phase: "connecting" };
    view.rerender(<HostedChat config={voice({ dictation: "browser" })} />);

    expect(recognition.stop).toHaveBeenCalled();
  });

  it("puts away a server dictation's leftover before a call starts", async () => {
    // A failed recording keeps its strip and its audio until retried or
    // discarded; a call starting over it would leave both behind.
    dictation.state = { phase: "failed" };
    render(<HostedChat config={voice({ dictation: "server" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    expect(dictation.actions.cancel).toHaveBeenCalled();
    expect(voiceCall.start).toHaveBeenCalled();
  });

  it("shows a pending approval without anything a visitor could decide it with", () => {
    voiceCall.call = {
      ...LIVE,
      activity: "awaiting_approval",
      approval: {
        id: "a1",
        tool: "send_invoice",
        args: { customer: "Acme" },
        said: null,
        deadline: Date.now() + 60_000,
        timeoutSeconds: 60,
      },
    };
    render(<HostedChat config={voice()} />);

    // The card is there, with what the agent asked to run...
    const card = screen.getByRole("group", { name: /Approve .*\?/ });
    expect(card).toHaveTextContent("Acme");
    // ...and nothing to decide it with.
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Deny/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show card" })).toBeNull();
    expect(voiceCall.decide).not.toHaveBeenCalled();
  });

  it("shows the live caption while the turn is spoken", () => {
    voiceCall.call = {
      ...LIVE,
      captions: [{ turnId: "c1:1:user", part: 0, role: "user", text: "Where is my", final: false }],
    };
    render(<HostedChat config={voice()} />);

    expect(screen.getByTestId("voice-captions-visible")).toHaveTextContent("Where is my");
  });

  it("puts a saved turn into the thread once, in place of its caption", () => {
    voiceCall.call = {
      ...LIVE,
      captions: [
        {
          turnId: "c1:1:user",
          part: 0,
          role: "user",
          text: "Where is my refund?",
          final: true,
        },
      ],
    };
    render(<HostedChat config={voice()} />);

    act(() => voiceCall.options.onTurnSaved?.(saved()));

    expect(screen.getAllByText("Where is my refund?")).toHaveLength(1);
    expect(screen.getByTestId("voice-captions-visible")).not.toHaveTextContent(
      "Where is my refund?",
    );
  });

  it("keeps a saved turn drawn once when the thread is read back afterwards", () => {
    voiceCall.call = {
      ...LIVE,
      captions: [
        { turnId: "c1:1:user", part: 0, role: "user", text: "Where is my refund?", final: true },
      ],
    };
    render(<HostedChat config={voice()} />);
    act(() => voiceCall.options.onTurnSaved?.(saved()));

    // A reconnect replays the thread, the call's turns included.
    act(() =>
      socket().deliver({
        type: "history",
        data: { messages: [{ role: "user", text: "Where is my refund?" }] },
      }),
    );

    expect(screen.getAllByText("Where is my refund?")).toHaveLength(1);
  });

  it("draws the agent's saved answer as the agent's", () => {
    voiceCall.call = LIVE;
    render(<HostedChat config={voice({ agent_name: "JARVIS" })} />);

    act(() =>
      voiceCall.options.onTurnSaved?.(
        saved({ role: "assistant", content: "It went out today.", turn_id: "c1:2:assistant" }),
      ),
    );

    expect(screen.getByText("It went out today.")).toBeInTheDocument();
    expect(screen.getByText("JARVIS")).toBeInTheDocument();
  });

  it("adds nothing for a turn saved with no words", () => {
    // An answer that only ran a tool: the transcript keeps the work, the page has no words to show.
    voiceCall.call = LIVE;
    render(<HostedChat config={voice({ welcome: "Ask about a refund." })} />);

    act(() =>
      voiceCall.options.onTurnSaved?.(saved({ role: "assistant", content: "", turn_id: "t2" })),
    );

    // The welcome stays: nothing joined the thread.
    expect(screen.getByText("Ask about a refund.")).toBeInTheDocument();
  });

  it("reopens the page's socket on the same visitor once the call names its thread", () => {
    // A first call creates the thread; the page's own socket, opened before it,
    // would otherwise answer the next typed message in a thread of its own.
    render(<HostedChat config={voice()} />);
    const first = socket();

    act(() => voiceCall.options.onConversation?.("conv-1"));

    expect(socket()).not.toBe(first);
    expect(first.close).toHaveBeenCalled();
    expect(socket().url).toBe(first.url);
  });

  it("leaves a thread already on screen alone when a call joins it", () => {
    // The socket is in the thread already; reopening it would replay the
    // history over the thread on screen and lose its steps and notices.
    render(<HostedChat config={voice()} />);
    const first = socket();
    act(() =>
      first.deliver({ type: "history", data: { messages: [{ role: "user", text: "Hi" }] } }),
    );

    act(() => voiceCall.options.onConversation?.("conv-1"));

    expect(socket()).toBe(first);
    expect(first.close).not.toHaveBeenCalled();
  });

  it("leaves the socket alone once the visitor has written in the thread", async () => {
    render(<HostedChat config={voice()} />);
    const first = socket();
    await userEvent.type(screen.getByRole("textbox"), "hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    act(() => voiceCall.options.onConversation?.("conv-1"));

    expect(socket()).toBe(first);
  });

  it("reopens the socket once for a call in a new chat", async () => {
    const view = render(<HostedChat config={voice()} />);
    act(() =>
      socket().deliver({ type: "history", data: { messages: [{ role: "user", text: "Hi" }] } }),
    );
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));
    voiceCall.call = { ...initialCall, phase: "connecting" };
    view.rerender(<HostedChat config={voice()} />);
    const fresh = socket();

    act(() => voiceCall.options.onConversation?.("conv-2"));
    expect(socket()).not.toBe(fresh);
    const reopened = socket();
    act(() => voiceCall.options.onConversation?.("conv-2"));
    expect(socket()).toBe(reopened);
  });

  it("says why a call did not start in words for a visitor, with a way to try again", async () => {
    voiceCall.call = { ...initialCall, phase: "ended", failure: "mic_insecure" };
    render(<HostedChat config={voice()} />);

    expect(
      screen.getByText(/Browsers allow it only on secure \(HTTPS\) pages/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/administrator/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(voiceCall.start).toHaveBeenCalled();
  });

  it("names no setup when the server refuses the call", () => {
    voiceCall.call = { ...initialCall, phase: "ended", endReason: "not_priced" };
    render(<HostedChat config={voice()} />);

    expect(screen.getByText(/Calls aren't available here right now/)).toBeInTheDocument();
    expect(screen.queryByText(/price/)).toBeNull();
  });

  it("puts the call's summary away once the visitor types on", async () => {
    voiceCall.call = { ...LIVE, phase: "ended", endReason: "user", endedAt: Date.now() };
    render(<HostedChat config={voice()} />);

    await userEvent.type(screen.getByRole("textbox"), "one more thing");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(voiceCall.dismiss).toHaveBeenCalled();
  });

  it("calls again from the summary of a call that ended", async () => {
    voiceCall.call = { ...LIVE, phase: "ended", endReason: "user", endedAt: Date.now() };
    render(<HostedChat config={voice({ voice_transport: "relay" })} />);

    await userEvent.click(screen.getByRole("button", { name: "Call again" }));

    expect(voiceCall.start).toHaveBeenCalledWith(expect.objectContaining({ transport: "relay" }));
  });

  it("puts focus back in the box when the call ends, if the bar took it with it", () => {
    voiceCall.call = LIVE;
    const view = render(<HostedChat config={voice()} />);
    expect(screen.getByRole("group", { name: "Voice call" })).toHaveFocus();

    voiceCall.call = { ...LIVE, phase: "ended", endReason: "user", endedAt: Date.now() };
    view.rerender(<HostedChat config={voice()} />);

    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("leaves focus where the visitor put it during the call", () => {
    voiceCall.call = LIVE;
    const view = render(<HostedChat config={voice({ allow_new_conversation: true })} />);
    const elsewhere = screen.getByRole("button", { name: "New chat" });
    elsewhere.focus();

    voiceCall.call = { ...LIVE, phase: "ended", endReason: "user", endedAt: Date.now() };
    view.rerender(<HostedChat config={voice({ allow_new_conversation: true })} />);

    expect(elsewhere).toHaveFocus();
  });

  it("hangs the call up when the visitor starts a new chat", async () => {
    voiceCall.call = LIVE;
    render(<HostedChat config={voice()} />);
    expect(screen.getByRole("group", { name: "Voice call" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(voiceCall.end).toHaveBeenCalled();
    expect(voiceCall.dismiss).toHaveBeenCalled();
  });

  it("keeps a call's late turns out of the new chat the visitor started", async () => {
    // Ending a call flushes the answer in progress as a saved turn; it belongs
    // to the thread the visitor left, not the empty one they opened.
    voiceCall.call = LIVE;
    const view = render(<HostedChat config={voice({ welcome: "Ask about a refund." })} />);
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    voiceCall.call = { ...LIVE, phase: "ended", endReason: "user", endedAt: Date.now() };
    view.rerender(<HostedChat config={voice({ welcome: "Ask about a refund." })} />);

    act(() =>
      voiceCall.options.onTurnSaved?.(
        saved({ role: "assistant", content: "It went out to", turn_id: "c1:2:assistant" }),
      ),
    );
    act(() => voiceCall.options.onConversation?.("conv-1"));

    expect(screen.queryByText("It went out to")).toBeNull();
    expect(screen.getByText("Ask about a refund.")).toBeInTheDocument();
  });

  it("draws a caption with the faces the page's own turns have", () => {
    voiceCall.call = {
      ...LIVE,
      captions: [
        { turnId: "c1:1:user", part: 0, role: "user", text: "Where is it", final: true },
        { turnId: "c1:2:assistant", part: 0, role: "assistant", text: "Let me", final: false },
      ],
    };
    render(<HostedChat config={voice({ agent_name: "JARVIS" })} />);

    const captions = screen.getByTestId("voice-captions-visible");
    expect(captions.querySelector(".lucide-user")).not.toBeNull();
    expect(captions.querySelector(".lucide-bot")).toBeNull();
    expect(captions).toHaveTextContent("J");
  });

  it("draws the operator's logo on the agent's caption when the page has one", () => {
    voiceCall.call = {
      ...LIVE,
      captions: [
        { turnId: "c1:2:assistant", part: 0, role: "assistant", text: "Let me", final: false },
      ],
    };
    render(<HostedChat config={voice({ logo_url: "/logo.png" })} />);

    const logo = screen.getByTestId("voice-captions-visible").querySelector("img");
    expect(logo?.getAttribute("src")).toBe("/api/embed/pk_abc/logo");
  });

  it.each([
    ["revoked", "Calls were switched off here.", /your access/],
    ["budget", "This assistant can't take calls right now.", /budget/i],
    ["guardrail", "The call was ended by a content rule.", /guardrail/i],
  ] as const)(
    "says how a live call that ended as %s ended in a visitor's words",
    (endReason, said, unsaid) => {
      voiceCall.call = { ...LIVE, phase: "ended", endReason, endedAt: Date.now() };
      render(<HostedChat config={voice()} />);

      expect(screen.getByTestId("voice-call-end")).toHaveTextContent(said);
      expect(document.body).not.toHaveTextContent(unsaid);
    },
  );

  it("says a limit is ending the call without naming the budget", () => {
    voiceCall.call = { ...LIVE, notice: "budget" };
    render(<HostedChat config={voice()} />);

    expect(screen.getByText("Ending: calls aren't available right now")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Calls aren't available right now. The call is ending.",
    );
    expect(document.body).toHaveTextContent("The assistant is saying so, then the call ends.");
    expect(document.body).not.toHaveTextContent(/budget/i);
  });

  it("announces a content rule cutting the answer off in a visitor's words", () => {
    voiceCall.call = { ...LIVE, notice: "guardrail" };
    render(<HostedChat config={voice()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("A content rule cut the answer off.");
    expect(document.body).not.toHaveTextContent(/guardrail/i);
  });
});
