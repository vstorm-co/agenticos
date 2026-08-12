import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HostedChat } from "./hosted-chat";
import type { HostedPageConfig } from "@/types/hosted";

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
    ...overrides,
  };
}

beforeEach(() => {
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
    await userEvent.click(screen.getByRole("button"));

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
        messages: [
          { role: "user", text: "do you ship to Poland?" },
          { role: "assistant", text: "we do" },
        ],
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
    await userEvent.click(screen.getByRole("button"));

    const frame = JSON.parse(socket().sent[0]!);
    expect(frame.context).toEqual({ plan: "pro" });
  });

  it("shows the answer and stops saying it is working", async () => {
    render(<HostedChat config={config()} />);

    await userEvent.type(screen.getByRole("textbox"), "hello");
    await userEvent.click(screen.getByRole("button"));
    act(() => socket().deliver({ type: "typing" }));
    expect(screen.getByText("Working on it…")).toBeInTheDocument();

    act(() => socket().deliver({ type: "message", role: "assistant", text: "30 days" }));

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
