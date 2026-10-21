import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentSelectionStore } from "@/stores/agent-selection-store";

import { QuickAsk } from "./quick-ask";

const env = vi.hoisted(() => ({
  auth: { isAuthenticated: true, isLoading: false },
  chat: {
    messages: [] as { role: string; content: string; isStreaming?: boolean }[],
    isProcessing: false,
    sendMessage: vi.fn(),
    clearMessages: vi.fn(),
  },
  created: null as null | ((id: string) => void),
  listeners: new Map<string, (payload?: unknown) => void>(),
  dictation: {
    engine: "server" as string,
    state: { phase: "idle" as string, transcript: null as null | { id: number; text: string } },
    actions: { start: vi.fn(async () => {}), stop: vi.fn() },
    agent: undefined as string | null | undefined,
  },
  commands: {
    hideQuickAsk: vi.fn(async () => {}),
    openInConsole: vi.fn(async () => {}),
    resizeQuickAsk: vi.fn(async () => {}),
    showConsole: vi.fn(async () => {}),
  },
  report: vi.fn(),
  resize: null as null | ((entries: { contentRect: { height: number } }[]) => void),
}));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => env.auth }));
vi.mock("@/hooks/use-chat", () => ({
  useChat: (options: { onConversationCreated: (id: string) => void }) => {
    env.created = options.onConversationCreated;
    return env.chat;
  },
}));
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (event: string, handler: (payload?: unknown) => void) =>
    env.listeners.set(event, handler),
}));
vi.mock("@/hooks/use-agent-dictation", () => ({
  useAgentDictation: (agent: string | null) => {
    env.dictation.agent = agent;
    return env.dictation;
  },
}));
vi.mock("@/lib/desktop/commands", () => env.commands);
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
vi.mock("@/components/chat/agent-picker", () => ({
  AgentPicker: () => <button type="button">Support</button>,
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

class CapturingResizeObserver {
  constructor(callback: (entries: { contentRect: { height: number } }[]) => void) {
    env.resize = callback;
  }
  observe = vi.fn();
  disconnect = vi.fn();
}

const question = () => screen.getByRole("textbox", { name: "Ask anything" });

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", CapturingResizeObserver);
  env.auth = { isAuthenticated: true, isLoading: false };
  env.chat.messages = [];
  env.chat.isProcessing = false;
  env.listeners.clear();
  env.dictation.engine = "server";
  env.dictation.state = { phase: "idle", transcript: null };
  useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
  vi.clearAllMocks();
});

afterEach(() => vi.unstubAllGlobals());

describe("QuickAsk", () => {
  it("asks on Enter, and keeps Shift+Enter for a new line", async () => {
    render(<QuickAsk />);
    expect(question()).toHaveFocus();
    await userEvent.type(question(), "What is our refund policy?{Shift>}{Enter}{/Shift}");
    expect(env.chat.sendMessage).not.toHaveBeenCalled();
    await userEvent.keyboard("{Enter}");
    expect(env.chat.sendMessage).toHaveBeenCalledWith("What is our refund policy?");
    expect(question()).toHaveValue("");
  });

  it("asks nothing empty, and nothing while the last answer is still coming", async () => {
    render(<QuickAsk />);
    await userEvent.type(question(), "   {Enter}");
    env.chat.isProcessing = true;
    await userEvent.type(question(), "x{Enter}");
    expect(env.chat.sendMessage).not.toHaveBeenCalled();
  });

  it("streams the answer under the question, and says it is thinking before it starts", () => {
    env.chat.messages = [{ role: "user", content: "Hi" }];
    env.chat.isProcessing = true;
    const { rerender } = render(<QuickAsk />);
    expect(screen.getAllByText("Thinking").length).toBeGreaterThan(0);
    env.chat.messages = [
      ...env.chat.messages,
      { role: "assistant", content: "30 days.", isStreaming: true },
    ];
    rerender(<QuickAsk />);
    expect(screen.getByText("30 days.")).toBeInTheDocument();
  });

  it("carries the conversation into the console with ⌘↩ or the button, and puts itself away", async () => {
    env.chat.messages = [{ role: "user", content: "Hi" }];
    render(<QuickAsk />);
    const carry = screen.getByRole("button", { name: /Continue in the console/ });
    expect(carry).toBeDisabled();
    act(() => env.created?.("c-1"));
    await userEvent.click(carry);
    expect(env.commands.openInConsole).toHaveBeenCalledWith("/chat?id=c-1");
    question().focus();
    await userEvent.keyboard("{Meta>}{Enter}{/Meta}");
    expect(env.commands.openInConsole).toHaveBeenCalledTimes(2);
    expect(env.commands.hideQuickAsk).toHaveBeenCalledTimes(2);
  });

  it("goes away on Escape, starts over on ⌘N and focuses itself when summoned", async () => {
    render(<QuickAsk />);
    await userEvent.type(question(), "draft");
    await userEvent.keyboard("{Control>}n{/Control}");
    expect(env.chat.clearMessages).toHaveBeenCalled();
    expect(question()).toHaveValue("");
    await userEvent.keyboard("{Meta>}{Enter}{/Meta}");
    expect(env.commands.openInConsole).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    expect(env.commands.hideQuickAsk).toHaveBeenCalled();
    question().blur();
    act(() => env.listeners.get("desktop:quick-ask")?.());
    expect(question()).toHaveFocus();
  });

  it("grows its window with the panel", () => {
    render(<QuickAsk />);
    act(() => env.resize?.([{ contentRect: { height: 240.4 } }]));
    act(() => env.resize?.([]));
    expect(env.commands.resizeQuickAsk).toHaveBeenCalledTimes(1);
    expect(env.commands.resizeQuickAsk).toHaveBeenCalledWith(241);
  });

  it("asks somebody signed out to sign in in the console", async () => {
    env.auth = { isAuthenticated: false, isLoading: false };
    render(<QuickAsk />);
    expect(question()).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Support" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open the console" }));
    expect(env.commands.showConsole).toHaveBeenCalled();
  });

  it("reports a command the shell refused", async () => {
    env.commands.hideQuickAsk.mockRejectedValueOnce(new Error("refused"));
    render(<QuickAsk />);
    question().focus();
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not put quick ask away", expect.any(Error)),
    );
  });

  describe("push to talk", () => {
    const press = (payload: unknown) => act(() => env.listeners.get("desktop:dictate")?.(payload));

    it("records for the selected agent while held, and stops when let go", () => {
      const view = render(<QuickAsk />);
      expect(env.dictation.agent).toBe("a-1");
      press("start");
      expect(env.dictation.actions.start).toHaveBeenCalledOnce();
      env.dictation.state = { phase: "recording", transcript: null };
      view.rerender(<QuickAsk />);
      expect(screen.getByRole("status")).toHaveTextContent("Listening - let go to stop");
      press("stop");
      expect(env.dictation.actions.stop).toHaveBeenCalled();
      env.dictation.state = { phase: "transcribing", transcript: null };
      view.rerender(<QuickAsk />);
      expect(screen.getByRole("status")).toHaveTextContent("Writing down what you said");
    });

    it("writes the words after what is typed, once per transcript", async () => {
      const view = render(<QuickAsk />);
      await userEvent.type(question(), "Hi");
      env.dictation.state = { phase: "idle", transcript: { id: 1, text: "what is due today" } };
      view.rerender(<QuickAsk />);
      view.rerender(<QuickAsk />);
      expect(question()).toHaveValue("Hi what is due today");
    });

    it("starts one recording however often a held key repeats, into an empty question", () => {
      const view = render(<QuickAsk />);
      press("start");
      env.dictation.state = { phase: "recording", transcript: null };
      view.rerender(<QuickAsk />);
      press("start");
      expect(env.dictation.actions.start).toHaveBeenCalledOnce();
      env.dictation.state = { phase: "idle", transcript: { id: 2, text: "what is due today" } };
      view.rerender(<QuickAsk />);
      expect(question()).toHaveValue("what is due today");
    });

    it("stops as the microphone opens when it was let go while being asked for", () => {
      const view = render(<QuickAsk />);
      press("start");
      env.dictation.state = { phase: "requesting", transcript: null };
      view.rerender(<QuickAsk />);
      press("stop");
      env.dictation.actions.stop.mockClear();
      env.dictation.state = { phase: "recording", transcript: null };
      view.rerender(<QuickAsk />);
      expect(env.dictation.actions.stop).toHaveBeenCalledOnce();
    });

    it("says why when the agent takes no dictation, until the person types", async () => {
      env.dictation.engine = "browser";
      render(<QuickAsk />);
      press("start");
      expect(env.dictation.actions.start).not.toHaveBeenCalled();
      expect(screen.getByRole("status")).toHaveTextContent("This agent takes no dictation");
      await userEvent.type(question(), "x");
      expect(screen.queryByRole("status")).toBeNull();
    });

    it("records for nobody while signed out, and reports a state it does not know", () => {
      env.auth = { isAuthenticated: false, isLoading: false };
      render(<QuickAsk />);
      expect(env.dictation.agent).toBeNull();
      press("sideways");
      expect(env.report).toHaveBeenCalledWith("an unknown push-to-talk state", "sideways");
    });
  });
});
