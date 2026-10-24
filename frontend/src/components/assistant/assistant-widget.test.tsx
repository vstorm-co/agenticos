import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toast } from "sonner";

import type { ChatPrompt } from "@/components/chat/chat-container";
import type { IncomingFiles } from "@/components/chat/chat-input";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { AssistantState } from "@/types/assistant";

import { BUBBLE_VISIBLE_MS } from "./assistant-bubble";
import { WidgetRoot } from "./assistant-launcher";
import { AssistantWidget, DOCK_AFTER_MS } from "./assistant-widget";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  pathname: "/agents",
  signals: {
    pendingApprovals: 0,
    noAgents: false,
    failedRunId: null as string | null,
    stuckIn: null as string | null,
  },
  push: vi.fn(),
  pointAt: vi.fn(),
  capture: vi.fn(),
  startNewChat: vi.fn(),
  selectConversation: vi.fn(),
  conversations: [] as { id: string; title?: string; created_at: string; updated_at: string }[],
  currentConversationId: null as string | null,
  phone: false,
}));

const CONSOLE_LINK = "/agents?highlight=agents-new";

// The chat itself is the console's own and tested where it lives; here it is
// what the window hands it - the prompt a bubble asked, the files attached, the
// welcome - and two links, one to the console and one away from it.
vi.mock("@/components/chat/chat-container", () => ({
  ChatContainer: ({
    prompt,
    incomingFiles,
    emptyState,
  }: {
    prompt: ChatPrompt | null;
    incomingFiles: IncomingFiles | null;
    emptyState: (onPick: (text: string) => void) => React.ReactNode;
  }) => (
    <div
      data-testid="chat"
      data-prompt={prompt?.text ?? ""}
      data-files={incomingFiles?.files.length ?? 0}
    >
      {emptyState(() => undefined)}
      <a href={CONSOLE_LINK}>console link</a>
      <a href="https://evil.example">outside link</a>
    </div>
  ),
}));
vi.mock("@/hooks/use-conversations", () => ({
  useConversations: () => ({
    startNewChat: state.startNewChat,
    conversations: state.conversations,
    currentConversationId: state.currentConversationId,
    fetchConversations: vi.fn(),
    selectConversation: state.selectConversation,
  }),
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({ assistant: state.assistant, isLoading: false }),
}));
vi.mock("@/hooks/use-assistant-signals", () => ({ useAssistantSignals: () => state.signals }));
vi.mock("@/lib/assistant-highlight", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/assistant-highlight")>()),
  pointAt: state.pointAt,
}));
vi.mock("@/lib/assistant-screenshot", () => ({ captureThisTab: state.capture }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: state.push }) }));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "ready",
    agent_id: "a1",
    slug: "ai-architect",
    name: "Architect",
    named_by_default: true,
    greeting: null,
    avatar_url: null,
    wears_mark: true,
    avatar_color: null,
    can_use: true,
    can_configure: false,
    ...overrides,
  };
}

/** Waits out the moment a page is looked at before the bubble speaks. */
function lookAtThePage() {
  act(() => {
    vi.advanceTimersByTime(3000);
  });
}

const chat = () => screen.getByTestId("chat");

beforeEach(() => {
  vi.useFakeTimers();
  state.assistant = assistant();
  state.pathname = "/agents";
  state.signals = { pendingApprovals: 0, noAgents: false, failedRunId: null, stuckIn: null };
  state.phone = false;
  state.conversations = [];
  state.currentConversationId = null;
  for (const fn of [
    state.push,
    state.pointAt,
    state.capture,
    state.startNewChat,
    state.selectConversation,
  ])
    fn.mockReset();
  vi.mocked(toast.error).mockReset();
  vi.mocked(toast).mockReset();
  window.matchMedia = ((query: string) => ({
    matches: state.phone,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as never;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("the Architect widget", () => {
  it.each([
    ["there is no assistant", null],
    ["the person may not run agents", { can_use: false }],
    ["it could not be installed", { status: "unavailable", agent_id: null }],
    ["it is switched off", { status: "disabled" }],
  ] as const)("is not there when %s", (_, overrides) => {
    state.assistant = overrides === null ? null : assistant(overrides as Partial<AssistantState>);
    const { container } = render(<AssistantWidget />);

    expect(container).toBeEmptyDOMElement();
  });

  it("is the Architect in the reader's language until it is renamed, and wears its mark", () => {
    // Installed beside an agent that took its handle: the name had to differ,
    // the console still calls it the Architect.
    state.assistant = assistant({ name: "Architect (AgenticOS)" });
    const { unmount } = render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open Architect" })).toBeInTheDocument();
    expect(document.querySelector('svg circle[fill="#2557d6"]')).not.toBeNull();
    unmount();

    state.assistant = assistant({
      name: "Ola z IT",
      named_by_default: false,
      avatar_url: "/api/agents/a1/avatar",
      wears_mark: false,
    });
    render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open Ola z IT" })).toBeInTheDocument();
    // Given a picture, it wears the picture.
    expect(document.querySelector('svg circle[fill="#2557d6"]')).toBeNull();
  });

  it("walks through connecting a model when it has none", () => {
    state.assistant = assistant({ status: "needs_model" });
    render(<AssistantWidget />);

    expect(screen.getByText(/I'm not connected to a model yet/)).toBeInTheDocument();
  });

  it("speaks to the page after a moment, and a click asks it in the window", () => {
    render(<AssistantWidget />);
    expect(screen.queryByText(/Want a new agent/)).toBeNull();

    lookAtThePage();
    // It says who is speaking - and no more: no label of what kind of bubble it is.
    expect(screen.queryByText("on this page")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Describe it" }));

    const dialog = screen.getByRole("dialog", { name: "Architect" });
    expect(dialog).not.toHaveClass("hidden");
    // The console's own chat, in the page - not a page framed inside it.
    expect(document.querySelector("iframe")).toBeNull();
    expect(chat()).toHaveAttribute("data-prompt", expect.stringMatching(/new agent/));
    expect(screen.queryByText(/Want a new agent/)).toBeNull();
  });

  it("opens and asks what somebody elsewhere in the console asked it, each ask once", () => {
    useArchitectAskStore.setState({ request: null });
    const { rerender } = render(<AssistantWidget />);

    act(() => useArchitectAskStore.getState().ask("Make an agent of this"));

    expect(screen.getByRole("dialog", { name: "Architect" })).not.toHaveClass("hidden");
    expect(chat()).toHaveAttribute("data-prompt", "Make an agent of this");

    fireEvent.click(screen.getByRole("button", { name: "Close", expanded: true }));
    rerender(<AssistantWidget />);
    expect(screen.getByRole("dialog", { name: "Architect" })).toHaveClass("hidden");
    expect(useArchitectAskStore.getState().request).toBeNull();

    act(() => useArchitectAskStore.getState().ask("And another"));
    expect(chat()).toHaveAttribute("data-prompt", "And another");
  });

  it("lets a bubble fade when nobody answers it, and holds it while the pointer rests on it", () => {
    render(<AssistantWidget />);
    lookAtThePage();
    const bubble = screen.getByRole("status");

    fireEvent.pointerEnter(bubble);
    act(() => {
      vi.advanceTimersByTime(BUBBLE_VISIBLE_MS * 2);
    });
    expect(screen.getByText(/Want a new agent/)).toBeInTheDocument();

    fireEvent.pointerLeave(bubble);
    act(() => {
      vi.advanceTimersByTime(BUBBLE_VISIBLE_MS);
    });
    expect(screen.queryByText(/Want a new agent/)).toBeNull();
    // Faded, not silenced: the page may speak again on another visit.
    const stored = localStorage.getItem("assistant-bubbles");
    expect(stored === null ? [] : JSON.parse(stored).silenced).toEqual([]);
  });

  it("tucks its button into the edge when left alone, and remembers it there", () => {
    const { unmount } = render(<AssistantWidget />);
    const launcher = screen.getByRole("button", { name: "Open Architect" });
    act(() => {
      vi.advanceTimersByTime(DOCK_AFTER_MS - 1000);
    });
    // The pointer passing over it is the reader still being about.
    fireEvent.pointerEnter(launcher);
    act(() => {
      vi.advanceTimersByTime(DOCK_AFTER_MS - 1000);
    });
    expect(launcher).not.toHaveAttribute("data-docked");

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(launcher).toHaveAttribute("data-docked");
    unmount();

    // Another page, another visit: still tucked away, and quiet.
    render(<AssistantWidget />);
    lookAtThePage();
    expect(screen.getByRole("button", { name: "Open Architect" })).toHaveAttribute("data-docked");
    expect(screen.queryByText(/Want a new agent/)).toBeNull();
  });

  it("comes out of the edge when it is opened, and marks what waits while it is tucked away", () => {
    localStorage.setItem("assistant-bubbles", JSON.stringify({ docked: true }));
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    const launcher = screen.getByRole("button", { name: "Open Architect" });
    expect(launcher.querySelector("span[aria-hidden]")).not.toBeNull();

    fireEvent.click(launcher);

    expect(launcher).not.toHaveAttribute("data-docked");
    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!).docked).toBe(false);
  });

  it("shows the earlier conversations and starts a new one from its header", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("button", { name: "Conversations" }));
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
    // The list's own button, then the header's.
    fireEvent.click(screen.getAllByRole("button", { name: "New conversation" })[1]!);
    expect(state.startNewChat).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("No conversations yet.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(state.startNewChat).toHaveBeenCalledTimes(2);
  });

  it("opens an earlier conversation from the list, and closes the list", () => {
    const now = new Date().toISOString();
    state.conversations = [
      { id: "c1", title: "Build a support bot", created_at: now, updated_at: now },
      { id: "c2", created_at: now, updated_at: "" },
    ];
    state.currentConversationId = "c1";
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("button", { name: "Conversations" }));
    expect(screen.getByRole("button", { name: /Untitled conversation/ })).toBeInTheDocument();
    // Filtered by title, as typed.
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "support" },
    });
    expect(screen.queryByRole("button", { name: /Untitled conversation/ })).toBeNull();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "nothing like it" },
    });
    expect(screen.getByText("No conversation matches.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Build a support bot/ }));
    expect(state.selectConversation).toHaveBeenCalledWith("c1");
    expect(screen.queryByRole("button", { name: /Untitled conversation/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Conversations" }));
    fireEvent.click(screen.getByRole("button", { name: "Back to the conversation" }));
    expect(screen.queryByRole("button", { name: /Untitled conversation/ })).toBeNull();
  });

  it("puts what is waiting first", () => {
    state.signals.pendingApprovals = 2;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/waiting for your approval/)).toBeInTheDocument();
  });

  it("keeps quiet in the chat, where the composer has its corner and no launcher shows", () => {
    state.signals.pendingApprovals = 2;
    state.pathname = "/chat";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
  });

  it("says what is waiting once a visit, not again on every page, until more arrives", () => {
    state.signals.pendingApprovals = 2;
    state.pathname = "/runs";
    const { rerender } = render(<AssistantWidget />);
    lookAtThePage();
    act(() => {
      vi.advanceTimersByTime(BUBBLE_VISIBLE_MS);
    });
    expect(screen.queryByText(/waiting for your approval/)).toBeNull();

    state.pathname = "/skills";
    rerender(<AssistantWidget />);
    lookAtThePage();
    expect(screen.queryByText(/waiting for your approval/)).toBeNull();

    state.signals.pendingApprovals = 3;
    state.pathname = "/agents";
    rerender(<AssistantWidget />);
    lookAtThePage();
    expect(screen.getByText(/waiting for your approval/)).toBeInTheDocument();
  });

  it("keeps approvals it has raised quiet after the console is reloaded", () => {
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    const { unmount } = render(<AssistantWidget />);
    lookAtThePage();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    unmount();

    // A link opened afresh: a new widget, the same tab.
    state.pathname = "/skills";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
  });

  it("marks what waits with a dot on a phone rather than covering the page", () => {
    state.phone = true;
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
    const launcher = screen.getByRole("button", { name: "Open Architect" });
    expect(launcher.querySelector("span[aria-hidden]")).not.toBeNull();
  });

  it("follows the window across the phone width", () => {
    let listener: (() => void) | null = null;
    window.matchMedia = ((query: string) => ({
      get matches() {
        return state.phone;
      },
      media: query,
      addEventListener: (_: string, handler: () => void) => {
        listener = handler;
      },
      removeEventListener: () => {},
    })) as never;
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();
    expect(screen.getByText(/waiting for your approval/)).toBeInTheDocument();

    state.phone = true;
    act(() => listener?.());

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
  });

  it("still speaks where the tab keeps nothing", () => {
    // On the storage objects themselves: `vitest.setup.ts` installs its own,
    // so a spy on `Storage.prototype` never reaches the read.
    vi.spyOn(sessionStorage, "getItem").mockImplementation((key: string) => {
      if (key === "assistant-approvals-heard") throw new Error("denied");
      return null;
    });
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
  });

  it("keeps waiting approvals quiet on the next page after Not now", () => {
    state.signals.pendingApprovals = 1;
    state.pathname = "/runs";
    const { rerender } = render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    state.pathname = "/skills";
    rerender(<AssistantWidget />);
    lookAtThePage();

    expect(screen.queryByText(/waiting for your approval/)).toBeNull();
  });

  it("offers the first steps to an organization with no agents", () => {
    state.signals.noAgents = true;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/no agents yet/)).toBeInTheDocument();
  });

  it("raises a failed run once, asking about that run", () => {
    state.signals.failedRunId = "run-7";
    const { rerender } = render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Explain it" }));
    expect(chat()).toHaveAttribute("data-prompt", expect.stringContaining("run-7"));

    fireEvent.click(screen.getByRole("button", { name: "Close", expanded: true }));
    rerender(<AssistantWidget />);
    expect(screen.queryByText(/One of your runs failed/)).toBeNull();
  });

  it("lets a failed run be waved away without asking", () => {
    state.signals.failedRunId = "run-8";
    render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Don't show tips on this page" }));

    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!).seenRun).toBe("run-8");
  });

  it("sets the bubble aside for this visit with Not now, without silencing the page", () => {
    render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(screen.queryByText(/Want a new agent/)).toBeNull();
    const stored = localStorage.getItem("assistant-bubbles");
    expect(stored === null ? [] : JSON.parse(stored).silenced).toEqual([]);
  });

  it("offers help with a form somebody is stuck in, by its name", () => {
    state.signals.stuckIn = "Create a knowledge base";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/Stuck on "Create a knowledge base"/)).toBeInTheDocument();
  });

  it("opens a page the Architect linked to and points at the control it named", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("link", { name: "console link" }));

    expect(state.push).toHaveBeenCalledWith("/agents");
    expect(state.pointAt).toHaveBeenCalledWith("agents-new");
    expect(screen.getByRole("dialog")).not.toHaveClass("hidden");
  });

  it("steps the window aside on a phone so the linked page is seen", () => {
    state.phone = true;
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("link", { name: "console link" }));

    expect(state.push).toHaveBeenCalledWith("/agents");
    expect(screen.getByRole("dialog")).toHaveClass("hidden");
  });

  it("leaves a link to anywhere but the console to the browser", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("link", { name: "outside link" }));

    expect(state.push).not.toHaveBeenCalled();
  });

  it("attaches a screenshot of the page, taken with the window out of the way", async () => {
    const file = new File(["png"], "shot.png", { type: "image/png" });
    let hiddenWhileTaken = false;
    state.capture.mockImplementation(async () => {
      hiddenWhileTaken = screen.getByRole("dialog").classList.contains("hidden");
      return file;
    });
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Show it this page" }));
    });

    expect(hiddenWhileTaken).toBe(true);
    expect(chat()).toHaveAttribute("data-files", "1");
    expect(screen.getByRole("dialog")).not.toHaveClass("hidden");
  });

  it("sends nothing when the person declines to share the page, and says so when it breaks", async () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    state.capture.mockResolvedValueOnce(null);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Show it this page" }));
    });
    expect(chat()).toHaveAttribute("data-files", "0");

    state.capture.mockRejectedValueOnce(new Error("no"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Show it this page" }));
    });
    expect(toast.error).toHaveBeenCalled();
  });

  it("keeps its presses from reaching an open dialog, which would close on them", () => {
    const outside = vi.fn();
    document.addEventListener("pointerdown", outside);
    render(<AssistantWidget />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Open Architect" }));

    expect(outside).not.toHaveBeenCalled();
    document.removeEventListener("pointerdown", outside);
  });

  it("lets its own controls have the press first, so a menu opening on it opens", () => {
    // The composer's `+` is a menu that opens on pointerdown; a listener that
    // stopped the press before React saw it left it dead in the window.
    const pressed = vi.fn();
    render(
      <WidgetRoot>
        <button type="button" onPointerDown={pressed}>
          Add to message
        </button>
      </WidgetRoot>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "Add to message" }));

    expect(pressed).toHaveBeenCalledOnce();
  });

  it("stays quiet on a page somebody silenced", () => {
    render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Don't show tips on this page" }));

    expect(screen.queryByText(/Want a new agent/)).toBeNull();
  });

  it("turns the bubbles off and on from its header", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));

    fireEvent.click(screen.getByRole("button", { name: "Turn tips off" }));
    expect(screen.getByRole("button", { name: "Turn tips back on" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Said, so the bell is not a button that seems to do nothing.
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/Tips are off/));
    fireEvent.click(screen.getByRole("button", { name: "Close", expanded: true }));
    lookAtThePage();
    expect(screen.queryByText(/Want a new agent/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn tips back on" }));
    expect(screen.getByRole("button", { name: "Turn tips off" })).toBeInTheDocument();
  });

  it("steps its button aside while the window is open, which takes its corner", () => {
    render(<AssistantWidget />);
    const launcher = screen.getByRole("button", { name: "Open Architect" });

    fireEvent.click(launcher);

    expect(launcher).toHaveClass("hidden");
    expect(launcher).not.toHaveClass("md:block");
  });

  it("steps out of the chat's composer on any screen, and stays on every other page", () => {
    // The corner it sits in is the composer's send controls there (#2075).
    state.pathname = "/pl/chat";
    const { unmount } = render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open Architect" })).toHaveClass("hidden");
    unmount();

    state.pathname = "/agents";
    render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open Architect" })).not.toHaveClass("hidden");
  });

  it("hides the window from its header without losing the conversation", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open Architect" }));
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);

    expect(dialog).toHaveClass("hidden");
  });
});
