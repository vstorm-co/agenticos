import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ASK, CONTEXT, HISTORY, NEW } from "@/lib/assistant-messages";
import type { AssistantState } from "@/types/assistant";

import { AssistantWidget } from "./assistant-widget";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  pathname: "/agents",
  agents: [{ id: "x" }] as { id: string }[],
  agentsLoading: false,
  approvals: 0,
  defaultLocale: "en",
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({ assistant: state.assistant, isLoading: false }),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => true }),
  useAgents: () => ({ agents: state.agents, isLoading: state.agentsLoading }),
  useApprovals: () => ({ total: state.approvals }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
// The reader's locale is always "en" under the test translator, so a reader on
// another one is the default locale moving instead.
vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  get defaultLocale() {
    return state.defaultLocale;
  },
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

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
  state.agents = [{ id: "x" }];
  state.agentsLoading = false;
  state.approvals = 0;
  state.defaultLocale = "en";
});

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
    state.approvals = 2;
    state.pathname = "/runs";
    render(<AssistantWidget />);
    lookAtThePage();

    expect(screen.getByText(/waiting for your approval/)).toBeInTheDocument();
  });

  it("offers the first steps to an organization with no agents, once they have loaded", () => {
    state.agents = [];
    state.agentsLoading = true;
    state.pathname = "/runs";
    const { rerender } = render(<AssistantWidget />);
    lookAtThePage();
    expect(screen.queryByText(/no agents yet/)).toBeNull();

    state.agentsLoading = false;
    rerender(<AssistantWidget />);

    expect(screen.getByText(/no agents yet/)).toBeInTheDocument();
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

  it("hides the window from its header without losing the conversation", () => {
    render(<AssistantWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);

    expect(dialog).toHaveClass("hidden");
  });
});
