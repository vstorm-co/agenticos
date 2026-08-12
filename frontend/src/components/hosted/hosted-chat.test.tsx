import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HostedChat } from "./hosted-chat";
import type { HostedPageConfig } from "@/types/hosted";

// The real renderer is loaded with `next/dynamic` and `ssr: false`, so under
// jsdom it renders its own placeholder and every assertion on an answer's words
// would be asserting on a non-breaking space. What it renders is tested where it
// lives; what matters here is that the answer reaches it at all.
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <span>{content}</span>,
}));

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
    allow_voice: false,
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

  it("shows the welcome message before the first question", () => {
    render(<HostedChat config={config({ welcome: "Ask about a refund." })} />);

    expect(screen.getByText("Ask about a refund.")).toBeInTheDocument();
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

    expect(screen.getByText("30 days")).toBeInTheDocument();
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
    render(<HostedChat config={config({ allow_voice: false })} />);

    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
  });

  it("offers no microphone in a browser that has none, even when allowed", () => {
    // A control that cannot work is not rendered - the same rule the dashboard
    // applies to a permission somebody lacks.
    render(<HostedChat config={config({ allow_voice: true })} />);

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

    render(<HostedChat config={config({ allow_voice: true })} />);
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

  it("opens a step into what came back, when the server sent it", () => {
    render(<HostedChat config={config()} />);

    act(() =>
      socket().deliver({
        type: "tool_call",
        data: { tool_call_id: "c1", tool_name: "search_documents" },
      }),
    );
    act(() =>
      socket().deliver({ type: "tool_result", data: { tool_call_id: "c1", content: "30 days" } }),
    );

    expect(screen.getByText("30 days")).toBeInTheDocument();
  });

  it("renders the reasoning it was sent, and nothing where it was not", () => {
    // The page has no branch that hides it: a page whose operator left
    // `show_thinking` off never receives the frame, which is what makes the
    // setting mean something on a surface with devtools.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "thinking_delta", data: { content: "Checking policy." } }));

    expect(screen.getByText("Checking policy.")).toBeInTheDocument();
  });

  it("keeps one bubble for a turn rather than one per frame", () => {
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "Thirty " } }));
    act(() => socket().deliver({ type: "text_delta", data: { content: "days." } }));

    expect(screen.getByText("Thirty days.")).toBeInTheDocument();
  });

  it("starts a new bubble once a turn is over", () => {
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "text_delta", data: { content: "First." } }));
    act(() => socket().deliver({ type: "complete", data: {} }));
    act(() => socket().deliver({ type: "text_delta", data: { content: "Second." } }));

    expect(screen.getByText("First.")).toBeInTheDocument();
    expect(screen.getByText("Second.")).toBeInTheDocument();
  });

  it("settles on what the run ended with", () => {
    // A provider that streams no deltas leaves `final_result` as the only copy of
    // the answer, so it is assigned rather than appended.
    render(<HostedChat config={config()} />);

    act(() => socket().deliver({ type: "final_result", data: { output: "Thirty days." } }));

    expect(screen.getByText("Thirty days.")).toBeInTheDocument();
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
    // page, so an upload with no key is one the server cannot bound.
    expect(fetched.mock.calls[0]![0]).toMatch(/\/files\?visitor=[0-9a-f]{32}$/);

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
