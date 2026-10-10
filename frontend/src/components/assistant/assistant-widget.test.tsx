import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toast } from "sonner";

import { ASK, ATTACH, CONTEXT, HISTORY, NAVIGATE, NEW } from "@/lib/assistant-messages";
import type { AssistantState } from "@/types/assistant";

import { AssistantWidget } from "./assistant-widget";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  pathname: "/agents",
  signals: {
    pendingApprovals: 0,
    noAgents: false,
    failedRunId: null as string | null,
    stuckIn: null as string | null,
  },
  defaultLocale: "en",
  push: vi.fn(),
  pointAt: vi.fn(),
  capture: vi.fn(),
  phone: false,
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
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
// The reader's locale is always "en" under the test translator, so a reader on
// another one is the default locale moving instead.
vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  get defaultLocale() {
    return state.defaultLocale;
  },
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: state.push }) }));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "ready",
    agent_id: "a1",
    slug: "ai-architect",
    name: "AI Architect",
    greeting: null,
    avatar_url: null,
    avatar_color: null,
    model_profile_id: "m1",
    collection_ids: [],
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

/** The frame, loaded, with what it is sent recorded. */
function loadedFrame() {
  const frame = document.querySelector("iframe")!;
  const sent = vi.spyOn(frame.contentWindow!, "postMessage");
  fireEvent.load(frame);
  return { frame, sent };
}

beforeEach(() => {
  vi.useFakeTimers();
  state.assistant = assistant();
  state.pathname = "/agents";
  state.signals = { pendingApprovals: 0, noAgents: false, failedRunId: null, stuckIn: null };
  state.defaultLocale = "en";
  state.phone = false;
  for (const fn of [state.push, state.pointAt, state.capture]) fn.mockReset();
  vi.mocked(toast.error).mockReset();
  window.matchMedia = ((query: string) => ({ matches: state.phone, media: query })) as never;
});

/** The frame asking the console to open a page, as the frame's click handler does. */
function frameSays(data: unknown) {
  const source = document.querySelector("iframe")!.contentWindow;
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", { data, origin: window.location.origin, source }),
    );
  });
}

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

describe("the AI Architect widget", () => {
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

  it("walks through connecting a model when it has none", () => {
    state.assistant = assistant({ status: "needs_model" });
    render(<AssistantWidget />);

    expect(screen.getByText(/I'm not connected to a model yet/)).toBeInTheDocument();
  });

  it("speaks to the page after a moment, and a click asks it in the window", () => {
    render(<AssistantWidget />);
    expect(screen.queryByText(/Want a new agent/)).toBeNull();

    lookAtThePage();
    fireEvent.click(screen.getByText(/Want a new agent/));

    const dialog = screen.getByRole("dialog", { name: "AI Architect" });
    expect(dialog).not.toHaveClass("hidden");
    expect(document.querySelector("iframe")).toHaveAttribute("src", "/assistant-frame?agent=a1");
    const { sent } = loadedFrame();
    expect(sent.mock.calls.map(([message]) => message)).toEqual([
      expect.objectContaining({ type: CONTEXT, path: "/agents" }),
      expect.objectContaining({ type: CONTEXT, path: "/agents" }),
      { type: ASK, text: expect.stringMatching(/new agent/) },
    ]);
    expect(screen.queryByText(/Want a new agent/)).toBeNull();
  });

  it("opens the frame under the reader's locale", () => {
    state.defaultLocale = "pl";
    render(<AssistantWidget />);

    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    expect(document.querySelector("iframe")).toHaveAttribute("src", "/en/assistant-frame?agent=a1");
  });

  it("sends history and a new conversation straight to a loaded frame", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    const { sent } = loadedFrame();
    sent.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Conversations" }));
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));

    expect(sent.mock.calls.map(([message]) => message)).toEqual([{ type: HISTORY }, { type: NEW }]);
  });

  it("puts what is waiting first", () => {
    state.signals.pendingApprovals = 2;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/waiting for your approval/)).toBeInTheDocument();
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

    fireEvent.click(screen.getByText(/One of your runs failed/));
    const { sent } = loadedFrame();
    expect(sent.mock.calls.map(([message]) => message)).toContainEqual({
      type: ASK,
      text: expect.stringContaining("run-7"),
    });

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

  it("offers help with a form somebody is stuck in, by its name", () => {
    state.signals.stuckIn = "Create a knowledge base";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/Stuck on "Create a knowledge base"/)).toBeInTheDocument();
  });

  it("opens a page the Architect linked to and points at the control it named", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    frameSays({ type: NAVIGATE, href: "/agents?highlight=agents-new" });

    expect(state.push).toHaveBeenCalledWith("/agents");
    expect(state.pointAt).toHaveBeenCalledWith("agents-new");
    expect(screen.getByRole("dialog")).not.toHaveClass("hidden");
  });

  it("steps the window aside on a phone so the linked page is seen", () => {
    state.phone = true;
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    frameSays({ type: NAVIGATE, href: "/runs" });

    expect(state.push).toHaveBeenCalledWith("/runs");
    expect(state.pointAt).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveClass("hidden");
  });

  it("ignores a link to anywhere but the console, and a message from anything but its frame", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    frameSays({ type: NAVIGATE, href: "https://evil.example" });
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: NAVIGATE, href: "/agents" },
          origin: window.location.origin,
        }),
      );
    });

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
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    const { sent } = loadedFrame();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Show it this page" }));
    });

    expect(hiddenWhileTaken).toBe(true);
    expect(sent).toHaveBeenCalledWith({ type: ATTACH, file }, window.location.origin);
    expect(screen.getByRole("dialog")).not.toHaveClass("hidden");
  });

  it("sends nothing when the person declines to share the page, and says so when it breaks", async () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    const { sent } = loadedFrame();
    sent.mockClear();

    state.capture.mockResolvedValueOnce(null);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Show it this page" }));
    });
    expect(sent).not.toHaveBeenCalled();

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

    fireEvent.pointerDown(screen.getByRole("button", { name: "Open AI Architect" }));

    expect(outside).not.toHaveBeenCalled();
    document.removeEventListener("pointerdown", outside);
  });

  it("stays quiet on a page somebody silenced", () => {
    render(<AssistantWidget />);
    lookAtThePage();

    fireEvent.click(screen.getByRole("button", { name: "Don't show tips on this page" }));

    expect(screen.queryByText(/Want a new agent/)).toBeNull();
  });

  it("turns the bubbles off and on from its header", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    fireEvent.click(screen.getByRole("button", { name: "Turn tips off" }));
    expect(screen.getByRole("button", { name: "Turn tips back on" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Close", expanded: true }));
    lookAtThePage();
    expect(screen.queryByText(/Want a new agent/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn tips back on" }));
    expect(screen.getByRole("button", { name: "Turn tips off" })).toBeInTheDocument();
  });

  it("steps its button aside on a phone while the window is open", () => {
    render(<AssistantWidget />);
    const launcher = screen.getByRole("button", { name: "Open AI Architect" });

    fireEvent.click(launcher);

    expect(launcher).toHaveClass("hidden", "md:block");
  });

  it("steps out of a phone's chat composer, and stays on every other page", () => {
    // The corner it sits in is the composer's send controls there (#2075).
    state.pathname = "/pl/chat";
    const { unmount } = render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open AI Architect" })).toHaveClass("max-md:hidden");
    unmount();

    state.pathname = "/agents";
    render(<AssistantWidget />);
    expect(screen.getByRole("button", { name: "Open AI Architect" })).not.toHaveClass(
      "max-md:hidden",
    );
  });

  it("hides the window from its header without losing the conversation", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);

    expect(dialog).toHaveClass("hidden");
  });
});
