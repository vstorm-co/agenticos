import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ChatPrompt } from "@/components/chat/chat-container";
import { TestPanel } from "./test-panel";
import { useTestShortcut } from "./use-test-shortcut";
import { readTestPanel, TEST_PANEL_OPEN, writeTestPanel } from "@/lib/test-panel-state";
import type { AgentEnvironment, AgentSpec } from "@/types/agents";

const useAgentVersion = vi.fn();
vi.mock("@/hooks", () => ({ useAgentVersion: (...args: unknown[]) => useAgentVersion(...args) }));

// Each conversation as what the panel hands it: what answers, the pins, the
// question asked of both, the replays - and a record of every time one began.
const began: string[] = [];
interface StubProps {
  testing: { mode: string };
  pinned: readonly string[];
  onTogglePin: (text: string) => void;
  ask: ChatPrompt | null;
  replay: number;
}
function StubChat({ testing, pinned, onTogglePin, ask, replay }: StubProps) {
  useEffect(() => {
    began.push(testing.mode);
  }, [testing.mode]);
  return (
    <section
      aria-label={`chat ${testing.mode}`}
      data-ask={ask?.text ?? ""}
      data-replay={replay}
      data-pinned={pinned.join("|")}
    >
      <button type="button" onClick={() => onTogglePin("Refunds?")}>
        pin from {testing.mode}
      </button>
    </section>
  );
}
vi.mock("./test-chat", () => ({
  testingFromMode: (mode: string) => ({ mode }),
  TestChat: (props: StubProps) => <StubChat {...props} />,
}));

const chat = (mode: string) => screen.getByRole("region", { name: `chat ${mode}` });

const PRODUCTION = {
  id: "env-prod",
  agent_id: "a1",
  name: "production",
  version_id: "v3",
  version: 3,
  is_default: true,
} as AgentEnvironment;

const STAGING = { ...PRODUCTION, id: "env-stg", name: "staging", version: 4, is_default: false };
const DRAFT = { name: "Support", instructions: "Be brief." } as AgentSpec;

function open(props: Partial<Parameters<typeof TestPanel>[0]> = {}) {
  const onClose = vi.fn();
  render(
    <TestPanel
      agentId="a1"
      currentVersionId="v3"
      draftSpec={DRAFT}
      environments={[PRODUCTION]}
      saving={false}
      onClose={onClose}
      {...props}
    />,
  );
  return { onClose };
}

beforeEach(() => {
  window.localStorage.clear();
  began.length = 0;
});

describe("the Builder's test panel", () => {
  it("tries the draft by default, and leaves saying so to the conversation", () => {
    open();

    expect(chat("draft")).toBeInTheDocument();
    // What answers is the conversation's own opening line now (#2075).
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("says when the latest change is still being saved", () => {
    open({ saving: true });

    expect(screen.getByRole("status")).toHaveTextContent("Saving your latest change");
  });

  it("answers with an environment's version once it is chosen, and remembers it", async () => {
    open();

    await userEvent.click(screen.getByRole("combobox", { name: "What answers" }));
    await userEvent.click(await screen.findByRole("option", { name: "production (version 3)" }));

    expect(chat("env-prod")).toBeInTheDocument();
    expect(readTestPanel("a1").mode).toBe("env-prod");
  });

  it("falls back to the draft when the agent has nothing published, or the environment is gone", () => {
    writeTestPanel("a1", {
      open: true,
      width: 440,
      compareWidth: 880,
      mode: "env-prod",
      compare: "draft",
      pinned: [],
    });
    open({ currentVersionId: null });
    expect(chat("draft")).toBeInTheDocument();
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Compare two side by side" })).toBeNull();
  });

  it("starts the conversation over, and replays its last question", async () => {
    open();

    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(began).toEqual(["draft", "draft"]);

    await userEvent.click(screen.getByRole("button", { name: "Send the last message again" }));
    expect(chat("draft")).toHaveAttribute("data-replay", "1");
    // A single conversation is asked from its own box, as in /chat.
    expect(screen.queryByRole("textbox", { name: "Prompt" })).toBeNull();
  });

  it("keeps a question the conversation pins, and drops it when it is unpinned (#2075)", async () => {
    open();

    await userEvent.click(screen.getByRole("button", { name: "pin from draft" }));
    expect(readTestPanel("a1").pinned).toEqual(["Refunds?"]);
    expect(chat("draft")).toHaveAttribute("data-pinned", "Refunds?");

    await userEvent.click(screen.getByRole("button", { name: "pin from draft" }));
    expect(readTestPanel("a1").pinned).toEqual([]);
  });

  it("pins from the box two compared conversations share, once, and unpins", async () => {
    open({ environments: [PRODUCTION, STAGING] });
    await userEvent.click(screen.getByRole("button", { name: "Compare two side by side" }));
    const input = screen.getByRole("textbox", { name: "Prompt" });
    const pin = screen.getByRole("button", { name: "Pin a test prompt" });

    await userEvent.type(input, "Refunds?");
    await userEvent.click(pin);
    await userEvent.type(input, "Refunds?");
    await userEvent.click(pin);
    expect(screen.getAllByRole("button", { name: "Refunds?" })).toHaveLength(1);
    expect(readTestPanel("a1").pinned).toEqual(["Refunds?"]);

    await userEvent.click(screen.getByRole("button", { name: "Unpin Refunds?" }));
    expect(screen.queryByRole("button", { name: "Refunds?" })).toBeNull();
  });

  it("is resized from its edge, within bounds, and keeps the width", () => {
    open();
    const edge = screen.getByRole("separator", { name: "Resize the test panel" });

    fireEvent.pointerDown(edge, { clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 700 });
    fireEvent.pointerUp(window);

    expect(readTestPanel("a1").width).toBe(740);

    fireEvent.pointerDown(edge, { clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 5000 });
    fireEvent.pointerUp(window);
    expect(readTestPanel("a1").width).toBe(320);
  });

  it("compares two side by side, asks both at once, and stops comparing", async () => {
    open({ environments: [PRODUCTION, STAGING] });

    await userEvent.click(screen.getByRole("button", { name: "Compare two side by side" }));

    expect(chat("env-prod")).toBeInTheDocument();
    expect(readTestPanel("a1")).toMatchObject({ compare: "env-prod", width: 440 });
    expect(screen.getByRole("complementary")).toHaveStyle("--test-panel-width: 880px");
    expect(screen.getByRole("status")).toHaveTextContent("Ask both");

    await userEvent.click(screen.getByRole("combobox", { name: "Compared with" }));
    await userEvent.click(await screen.findByRole("option", { name: "staging (version 4)" }));
    expect(chat("env-stg")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Prompt" }), "Refunds?");
    await userEvent.click(screen.getByRole("button", { name: "Ask both" }));
    expect(chat("draft")).toHaveAttribute("data-ask", "Refunds?");
    expect(chat("env-stg")).toHaveAttribute("data-ask", "Refunds?");

    const edge = screen.getByRole("separator", { name: "Resize the test panel" });
    fireEvent.pointerDown(edge, { clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 0 });
    fireEvent.pointerUp(window);
    expect(readTestPanel("a1")).toMatchObject({ width: 440, compareWidth: 1400 });

    // Stopping gives the Builder back the room it had, not the comparison's.
    await userEvent.click(screen.getByRole("button", { name: "Compare two side by side" }));
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(readTestPanel("a1")).toMatchObject({ compare: null, width: 440, compareWidth: 1400 });
    expect(screen.getByRole("complementary")).toHaveStyle("--test-panel-width: 440px");
  });

  it("compares the draft with an environment when an environment answers", async () => {
    writeTestPanel("a1", {
      open: true,
      width: 440,
      compareWidth: 880,
      mode: "env-prod",
      compare: null,
      pinned: [],
    });
    open();

    await userEvent.click(screen.getByRole("button", { name: "Compare two side by side" }));

    expect(chat("draft")).toBeInTheDocument();
    expect(chat("env-prod")).toBeInTheDocument();
  });

  it("shows what the draft changes against the published version", async () => {
    useAgentVersion.mockReturnValue({
      version: { version: 3, spec: { name: "Support", instructions: "Be thorough." } },
      isLoading: false,
      error: null,
    });
    open();

    await userEvent.click(screen.getByRole("button", { name: "What the draft changes" }));

    expect(useAgentVersion).toHaveBeenCalledWith("a1", "v3");
    expect(await screen.findByText(/against version 3/)).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText(/against version 3/)).toBeNull();
  });

  it("says when the published version cannot be read, and waits for it", async () => {
    useAgentVersion.mockReturnValue({
      version: undefined,
      isLoading: false,
      error: new Error("x"),
    });
    open();
    await userEvent.click(screen.getByRole("button", { name: "What the draft changes" }));
    expect(screen.queryByText("+1")).toBeNull();
    cleanup();

    useAgentVersion.mockReturnValue({ version: undefined, isLoading: true, error: null });
    open();
    await userEvent.click(screen.getByRole("button", { name: "What the draft changes" }));
    expect(screen.queryByText("+1")).toBeNull();
  });

  it("closes", async () => {
    const { onClose } = open();

    await userEvent.click(screen.getByRole("button", { name: "Close the test panel" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("asks the Architect's corner widget to step aside while it is open", () => {
    open();
    expect(document.documentElement.hasAttribute(TEST_PANEL_OPEN)).toBe(true);

    cleanup();

    expect(document.documentElement.hasAttribute(TEST_PANEL_OPEN)).toBe(false);
  });
});

function ShortcutHost({ enabled, toggle }: { enabled: boolean; toggle: () => void }) {
  useTestShortcut(enabled, toggle);
  return (
    <div>
      <input aria-label="instructions" />
    </div>
  );
}

describe("the T shortcut", () => {
  it("toggles the panel, but not while typing, with a modifier, or under a dialog", () => {
    const toggle = vi.fn();
    render(<ShortcutHost enabled toggle={toggle} />);

    fireEvent.keyDown(window, { key: "t" });
    fireEvent.keyDown(window, { key: "T" });
    fireEvent.keyDown(window, { key: "x" });
    fireEvent.keyDown(window, { key: "t", metaKey: true });
    fireEvent.keyDown(screen.getByLabelText("instructions"), { key: "t" });
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.append(dialog);
    fireEvent.keyDown(window, { key: "t" });
    dialog.remove();

    expect(toggle).toHaveBeenCalledTimes(2);
  });

  it("is not there for someone who cannot edit the agent", () => {
    const toggle = vi.fn();
    render(<ShortcutHost enabled={false} toggle={toggle} />);

    fireEvent.keyDown(window, { key: "t" });

    expect(toggle).not.toHaveBeenCalled();
  });
});
