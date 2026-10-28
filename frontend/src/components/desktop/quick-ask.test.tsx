import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";

import { QuickAsk } from "./quick-ask";
import type { Mentionable } from "@/types/mention";
import type { ToolCall, PendingApproval, Decision, QueuedMessage } from "@/types";

const env = vi.hoisted(() => ({
  toastError: vi.fn(),
  mentionables: [] as Mentionable[],
  auth: { isAuthenticated: true, isLoading: false },
  chat: {
    messages: [] as {
      role: string;
      content: string;
      isStreaming?: boolean;
      toolCalls?: ToolCall[];
    }[],
    browses: [],
    isConnected: true,
    isStopping: false,
    stopGeneration: vi.fn(),
    pendingApproval: null as PendingApproval | null,
    sendResumeDecisions: vi.fn(),
    queuedMessages: [] as QueuedMessage[],
    cancelQueued: vi.fn(),
    retryQueued: vi.fn(),
    clearQueued: vi.fn(),
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
    quickAskPinned: vi.fn(async () => false),
    setQuickAskPinned: vi.fn(async () => {}),
    setQuickAskPickerOpen: vi.fn(async () => {}),
    hideQuickAsk: vi.fn(async () => {}),
    openInConsole: vi.fn(async () => {}),
    resizeQuickAsk: vi.fn(async () => {}),
    showConsole: vi.fn(async () => {}),
  },
  report: vi.fn(),
  takeFiles: vi.fn(async (): Promise<File[]> => []),
  allow: vi.fn(async () => {}),
  upload: vi.fn(async (file: File) => ({
    id: `f-${file.name}`,
    filename: file.name,
    mime_type: "application/pdf",
    size: 1,
    file_type: "pdf",
    preview: null,
  })),
  resize: null as null | ((entries: { contentRect: { height: number } }[]) => void),
}));
vi.mock("sonner", () => ({ toast: { error: env.toastError } }));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: () => ({ items: env.mentionables, isLoading: false, isError: false }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));
vi.mock("@/hooks/use-knowledge-bases", () => ({ useKnowledgeBaseFor: () => () => undefined }));
vi.mock("@/lib/desktop/readiness", () => ({ publishDesktopActivity: vi.fn(async () => {}) }));
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
vi.mock("@/lib/desktop/context", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/context")>()),
  takeContextFiles: env.takeFiles,
  openAccessibilitySettings: env.allow,
}));
vi.mock("@/lib/file-api", () => ({ uploadFile: env.upload }));
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

vi.mock("@/components/chat/message-list", () => ({
  MessageList: ({ messages }: { messages: typeof env.chat.messages }) => (
    <div>
      {messages.map((message, index) => (
        <div key={index}>
          <p>{message.content}</p>
          {message.toolCalls?.map((tool) => (
            <p key={tool.id}>{tool.name}</p>
          ))}
        </div>
      ))}
    </div>
  ),
}));
vi.mock("@/components/chat/tool-approval-dialog", () => ({
  ToolApprovalDialog: ({
    onDecisions,
    disabled,
  }: {
    onDecisions: (decisions: Decision[]) => void;
    disabled: boolean;
  }) => (
    <button disabled={disabled} onClick={() => onDecisions([{ type: "approve" }])}>
      Approve command
    </button>
  ),
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
  env.mentionables = [];
  env.chat.messages = [];
  env.chat.isProcessing = false;
  env.chat.isConnected = true;
  env.chat.pendingApproval = null;
  env.chat.queuedMessages = [];
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

  describe("what was in front", () => {
    const FOUND = {
      app: "Mail",
      window: "Refund for order 1182",
      selection: "Please refund me",
      clipboard: "order 1182",
      files: ["invoice.pdf"],
      accessibility: true,
    };
    const open = (payload: unknown) => act(() => env.listeners.get("desktop:quick-ask")?.(payload));

    it("sends the selection and the files with the question, the clipboard only when put on", async () => {
      env.takeFiles.mockResolvedValue([new File(["x"], "invoice.pdf")]);
      render(<QuickAsk />);
      open(FOUND);
      expect(screen.getByRole("button", { name: "Selection from Mail" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByRole("button", { name: "Clipboard" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
      await userEvent.type(question(), "Draft a reply{Enter}");
      await vi.waitFor(() => expect(env.chat.sendMessage).toHaveBeenCalled());
      expect(env.chat.sendMessage).toHaveBeenCalledWith(
        "Draft a reply\n\nSelected in Mail - Refund for order 1182:\n> Please refund me",
        ["f-invoice.pdf"],
        [expect.objectContaining({ id: "f-invoice.pdf" })],
      );
      expect(screen.queryByRole("button", { name: "Selection from Mail" })).toBeNull();
    });

    it("leaves off what was taken off, and adds the clipboard when put on", async () => {
      render(<QuickAsk />);
      open({ ...FOUND, window: null, files: [] });
      await userEvent.click(screen.getByRole("button", { name: "Selection from Mail" }));
      await userEvent.click(screen.getByRole("button", { name: "Clipboard" }));
      await userEvent.type(question(), "What is this?{Enter}");
      expect(env.chat.sendMessage).toHaveBeenCalledWith(
        "What is this?\n\nFrom the clipboard:\n> order 1182",
      );
      expect(env.takeFiles).not.toHaveBeenCalled();
    });

    it("asks nothing when the files cannot be attached, and says so", async () => {
      env.takeFiles.mockRejectedValueOnce(new Error("gone"));
      render(<QuickAsk />);
      open(FOUND);
      await userEvent.type(question(), "Summarise{Enter}");
      expect(await screen.findByText(/could not be attached/)).toBeInTheDocument();
      expect(env.chat.sendMessage).not.toHaveBeenCalled();
      expect(question()).toHaveValue("Summarise");
    });

    it("offers the permission it needs, and takes the files off on request", async () => {
      render(<QuickAsk />);
      open({ ...FOUND, selection: null, clipboard: null, accessibility: false });
      await userEvent.click(
        screen.getByRole("button", { name: "Let AgenticOS read what you select" }),
      );
      expect(env.allow).toHaveBeenCalled();
      await userEvent.click(screen.getByRole("button", { name: "1 file from Finder" }));
      await userEvent.type(question(), "Hi{Enter}");
      expect(env.chat.sendMessage).toHaveBeenCalledWith("Hi");
    });

    it("names no app it does not know, and reports a capture it cannot read", () => {
      render(<QuickAsk />);
      open({ ...FOUND, app: null });
      expect(
        screen.getByRole("button", { name: "Selection from another app" }),
      ).toBeInTheDocument();
      open("nonsense");
      expect(env.report).toHaveBeenCalledWith(
        "could not read what was in front",
        expect.anything(),
      );
      expect(screen.queryByRole("button", { name: "Selection from another app" })).toBeNull();
    });
  });
});

it("keeps user text, earlier answers, and tool activity through follow-up turns", () => {
  env.chat.messages = [
    { role: "user", content: "First question" },
    {
      role: "assistant",
      content: "First answer",
      toolCalls: [
        { id: "tool", name: "read_file", args: { path: "note.txt" }, status: "completed" },
      ],
    },
    { role: "user", content: "Follow-up question" },
    { role: "assistant", content: "Second answer", isStreaming: true },
  ];
  env.chat.isProcessing = true;
  render(<QuickAsk />);
  const transcript = screen.getByRole("region", { name: "Quick Ask conversation" });
  expect(transcript).toHaveTextContent("First question");
  expect(transcript).toHaveTextContent("First answer");
  expect(transcript).toHaveTextContent("read_file");
  expect(transcript).toHaveTextContent("Follow-up question");
  expect(transcript).toHaveTextContent("Second answer");
});

it("shows pending tool approval and lets the person stop the live run", async () => {
  env.chat.messages = [{ role: "user", content: "Run the task" }];
  env.chat.isProcessing = true;
  env.chat.pendingApproval = {
    runId: "run",
    messageId: null,
    actionRequests: [],
    reviewConfigs: [],
  };
  render(<QuickAsk />);
  await userEvent.click(screen.getByRole("button", { name: "Approve command" }));
  expect(env.chat.sendResumeDecisions).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
  expect(env.chat.stopGeneration).toHaveBeenCalled();
});

it("keeps the person's queued text visible while offline", () => {
  env.chat.isConnected = false;
  env.chat.queuedMessages = [{ id: "queued", content: "Keep this question until connected" }];
  render(<QuickAsk />);
  expect(screen.getByRole("region", { name: "Quick Ask conversation" })).toBeVisible();
  expect(screen.getByText("Keep this question until connected")).toBeVisible();
});

it("does not enable approval while the connection is unavailable", () => {
  env.chat.messages = [{ role: "user", content: "Run the task" }];
  env.chat.isConnected = false;
  env.chat.pendingApproval = {
    runId: "run",
    messageId: null,
    actionRequests: [],
    reviewConfigs: [],
  };
  render(<QuickAsk />);
  expect(screen.getByRole("button", { name: "Approve command" })).toBeDisabled();
});

it("follows new messages until the reader scrolls up", () => {
  env.chat.messages = [{ role: "user", content: "First" }];
  const view = render(<QuickAsk />);
  const transcript = screen.getByRole("region", { name: "Quick Ask conversation" });
  Object.defineProperty(transcript, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(transcript, "clientHeight", { value: 200, configurable: true });
  env.chat.messages = [...env.chat.messages, { role: "assistant", content: "An answer" }];
  view.rerender(<QuickAsk />);
  expect(transcript.scrollTop).toBe(1000);
  fireEvent.wheel(transcript, { deltaY: -1 });
  transcript.scrollTop = 400;
  env.chat.messages = [...env.chat.messages, { role: "user", content: "More text arrives" }];
  view.rerender(<QuickAsk />);
  expect(transcript.scrollTop).toBe(400);
});

it("picks @mentions with the keyboard and sends their identity to the agent", async () => {
  const item: Mentionable = { kind: "mcp", id: "drive", name: "Google Drive" };
  env.mentionables = [item];
  render(<QuickAsk />);
  await userEvent.type(question(), "Find in @Goo");
  expect(screen.getByRole("listbox")).toBeVisible();
  await userEvent.keyboard("{Enter}");
  expect(question()).toHaveValue("Find in @Google Drive ");
  expect(env.chat.sendMessage).not.toHaveBeenCalled();
  await userEvent.type(question(), "the document{Enter}");
  expect(env.chat.sendMessage).toHaveBeenCalledWith(
    "Find in @Google Drive the document",
    undefined,
    undefined,
    [item],
  );
});

it("Escape closes mentions before hiding the panel, and removing a token removes its identity", async () => {
  env.mentionables = [{ kind: "collection", id: "kb", name: "Contracts" }];
  render(<QuickAsk />);
  await userEvent.type(question(), "@Con");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(env.commands.hideQuickAsk).not.toHaveBeenCalled();
  await userEvent.clear(question());
  await userEvent.type(question(), "@Con{Tab}");
  await userEvent.clear(question());
  await userEvent.type(question(), "A plain question{Enter}");
  expect(env.chat.sendMessage).toHaveBeenCalledWith("A plain question");
});

it("starts a separate conversation from the visible action and returns focus to the composer", async () => {
  env.chat.messages = [{ role: "user", content: "Previous thread" }];
  useConversationStore.getState().setCurrentConversationId("old-thread");
  render(<QuickAsk />);
  act(() => env.created?.("old-thread"));
  await userEvent.type(question(), "discard this draft");
  await userEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(useConversationStore.getState().currentConversationId).toBeNull();
  expect(env.chat.clearMessages).toHaveBeenCalledOnce();
  expect(env.chat.clearQueued).toHaveBeenCalledOnce();
  expect(question()).toHaveValue("");
  expect(question()).toHaveFocus();
  expect(screen.getByRole("button", { name: /Continue in the console/ })).toBeDisabled();
  await userEvent.type(question(), "A different topic");
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(env.chat.sendMessage).toHaveBeenCalledWith("A different topic");
});

it("offers a visible dismiss action and leaves an existing conversation intact", async () => {
  render(<QuickAsk />);
  await userEvent.type(question(), "keep this draft");
  await userEvent.click(screen.getByRole("button", { name: "Close Quick Ask" }));
  expect(env.commands.hideQuickAsk).toHaveBeenCalledOnce();
  expect(env.chat.clearMessages).not.toHaveBeenCalled();
  expect(question()).toHaveValue("keep this draft");
});

describe("Quick Ask attachments and pin", () => {
  it("uploads a picked file, sends without text and clears the attachment", async () => {
    render(<QuickAsk />);
    const file = new File(["print(1)"], "example.py", { type: "text/x-python" });
    await userEvent.upload(screen.getByLabelText("Attach file", { selector: "input" }), file);
    expect(await screen.findByText("example.py")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(env.chat.sendMessage).toHaveBeenCalledWith(
      "Analyze the attached file(s)",
      ["f-example.py"],
      [expect.objectContaining({ filename: "example.py" })],
    );
    expect(screen.queryByText("example.py")).not.toBeInTheDocument();
  });

  it("pastes images and allows removing them without sending", async () => {
    render(<QuickAsk />);
    const image = new File(["png"], "clipboard.png", { type: "image/png" });
    fireEvent.paste(question(), { clipboardData: { files: [image] } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Remove.*clipboard.png/ })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /Remove.*clipboard.png/ }));
    expect(screen.queryByText("clipboard.png")).not.toBeInTheDocument();
    expect(env.chat.sendMessage).not.toHaveBeenCalled();
  });

  it("pins the native panel and can unpin it", async () => {
    render(<QuickAsk />);
    const pin = screen.getByRole("button", { name: "Keep Quick Ask on screen" });
    await userEvent.click(pin);
    expect(env.commands.setQuickAskPinned).toHaveBeenCalledWith(true);
    expect(await screen.findByRole("button", { name: "Unpin Quick Ask" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(screen.getByRole("button", { name: "Unpin Quick Ask" }));
    expect(env.commands.setQuickAskPinned).toHaveBeenLastCalledWith(false);
  });
});

it("keeps the draft when an attachment fails and reports the failure", async () => {
  env.upload.mockRejectedValueOnce(new Error("upload failed"));
  render(<QuickAsk />);
  await userEvent.type(question(), "Keep this question");
  await userEvent.upload(
    screen.getByLabelText("Attach file", { selector: "input" }),
    new File(["x"], "failed.txt"),
  );
  await waitFor(() => expect(screen.queryByText("failed.txt")).not.toBeInTheDocument());
  expect(question()).toHaveValue("Keep this question");
  expect(env.toastError).toHaveBeenCalledWith(expect.stringContaining("failed.txt"));
  expect(env.chat.sendMessage).not.toHaveBeenCalled();
});

it("blocks send and new chat until uploads finish, then allows starting fresh", async () => {
  let finish: ((file: Awaited<ReturnType<typeof env.upload>>) => void) | undefined;
  env.upload.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(<QuickAsk />);
  await userEvent.type(question(), "Draft");
  await userEvent.upload(
    screen.getByLabelText("Attach file", { selector: "input" }),
    new File(["x"], "pending.txt"),
  );
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
  await userEvent.keyboard("{Enter}");
  expect(env.chat.sendMessage).not.toHaveBeenCalled();
  await act(async () => {
    finish?.({
      id: "f1",
      filename: "pending.txt",
      mime_type: "text/plain",
      size: 1,
      file_type: "text",
      preview: null,
    });
  });
  await userEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(screen.queryByText("pending.txt")).not.toBeInTheDocument();
  expect(question()).toHaveValue("");
});

it("does not carry an in-flight upload into another account", async () => {
  let finish: ((file: Awaited<ReturnType<typeof env.upload>>) => void) | undefined;
  env.upload.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<QuickAsk />);
  fireEvent.paste(question(), { clipboardData: { files: [new File(["x"], "private.txt")] } });
  env.auth = { isAuthenticated: false, isLoading: false };
  view.rerender(<QuickAsk />);
  await act(async () => {
    finish?.({
      id: "f1",
      filename: "private.txt",
      mime_type: "text/plain",
      size: 1,
      file_type: "text",
      preview: null,
    });
  });
  expect(screen.queryByText("private.txt")).not.toBeInTheDocument();
  expect(env.chat.sendMessage).not.toHaveBeenCalled();
});

it("accepts files dropped on the panel", async () => {
  render(<QuickAsk />);
  fireEvent.drop(window, {
    dataTransfer: { types: ["Files"], files: [new File(["{}"], "data.json")] },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Remove.*data.json/ })).toBeInTheDocument(),
  );
  expect(env.upload).toHaveBeenCalledWith(expect.objectContaining({ name: "data.json" }));
});

it("rejects oversized files before reading or uploading them", async () => {
  render(<QuickAsk />);
  const file = new File(["x"], "huge.zip");
  Object.defineProperty(file, "size", { value: 1024 * 1024 * 1024 });
  fireEvent.paste(question(), { clipboardData: { files: [file] } });
  expect(env.upload).not.toHaveBeenCalled();
  expect(env.toastError).toHaveBeenCalledWith(expect.stringContaining("huge.zip"));
});

it("keeps a pin failure visible and does not pretend the window is pinned", async () => {
  env.commands.setQuickAskPinned.mockRejectedValueOnce(new Error("refused"));
  render(<QuickAsk />);
  const button = screen.getByRole("button", { name: "Keep Quick Ask on screen" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-pressed", "false");
  expect(env.toastError).toHaveBeenCalled();
});

it("guards the native file chooser and clears the guard on cancellation", async () => {
  render(<QuickAsk />);
  await userEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(env.commands.setQuickAskPickerOpen).toHaveBeenCalledWith(true);
  fireEvent(
    screen.getByLabelText("Attach file", { selector: "input" }),
    new Event("cancel", { bubbles: true }),
  );
  expect(env.commands.setQuickAskPickerOpen).toHaveBeenLastCalledWith(false);
  expect(question()).toHaveFocus();
});
