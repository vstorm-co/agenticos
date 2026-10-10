import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { TestFrame, testingFromMode } from "./test-frame";
import { ASK, NEW, PIN, REPLAY } from "@/lib/assistant-messages";
import { readTestPanel, writeTestPanel } from "@/lib/test-panel-state";
import { useChatStore } from "@/stores";

const { container, startNewChat, select } = vi.hoisted(() => ({
  container: vi.fn(),
  startNewChat: vi.fn(),
  select: vi.fn(),
}));

vi.mock("@/components/chat/chat-container", () => ({
  ChatContainer: (props: unknown) => {
    container(props);
    return null;
  },
}));
vi.mock("@/hooks/use-conversations", () => ({ useConversations: () => ({ startNewChat }) }));
const agentState: { agent: unknown } = {
  agent: { id: "a1", name: "Amigo", slug: "amigo", has_avatar: false, avatar_color: null },
};
vi.mock("@/hooks/use-agents", () => ({ useAgent: () => agentState }));
vi.mock("@/stores", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/stores")>();
  return {
    ...actual,
    useAgentSelectionStore: (pick: (state: { select: typeof select }) => unknown) =>
      pick({ select }),
  };
});

function send(data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, origin: window.location.origin }));
  });
}

const lastProps = () =>
  container.mock.calls.at(-1)![0] as {
    prompt: { text: string } | null;
    testing: unknown;
    pins: { pinned: readonly string[]; toggle: (text: string) => void };
    emptyState: (onPick: (prompt: string) => void) => React.ReactNode;
  };

describe("the test panel's frame", () => {
  it("chats with the agent being built, as a test", () => {
    const testing = { draft: true, environmentId: null };
    render(<TestFrame agentId="a1" testing={testing} />);

    expect(select).toHaveBeenCalledWith("a1");
    expect(lastProps().testing).toEqual(testing);
  });

  it("sends a pinned prompt, replays the last question and starts over", () => {
    render(<TestFrame agentId="a1" testing={{ draft: true, environmentId: null }} />);

    send({ type: ASK, text: "Refunds?" });
    expect(lastProps().prompt?.text).toBe("Refunds?");

    useChatStore.setState({
      messages: [
        { id: "1", role: "user", content: "first", timestamp: new Date() },
        { id: "2", role: "assistant", content: "answer", timestamp: new Date() },
        { id: "3", role: "user", content: "last", timestamp: new Date() },
      ],
    } as never);
    send({ type: REPLAY });
    expect(lastProps().prompt?.text).toBe("last");

    send({ type: NEW });
    expect(startNewChat).toHaveBeenCalled();
  });

  it("replays nothing before anything was asked, and ignores a stranger", () => {
    useChatStore.setState({ messages: [] } as never);
    render(<TestFrame agentId="a1" testing={{ draft: true, environmentId: null }} />);

    send({ type: REPLAY });
    send({ type: "elsewhere" });

    expect(lastProps().prompt).toBeNull();
  });
});

describe("the frame's opening, as /chat's (#2075)", () => {
  beforeEach(() => window.localStorage.clear());

  it("names the agent and what answers, then its pinned questions and the starters", () => {
    writeTestPanel("a1", { ...readTestPanel("a1"), pinned: ["Refunds?"] });
    render(<TestFrame agentId="a1" testing={{ draft: true, environmentId: null }} />);
    const onPick = vi.fn();
    render(<>{lastProps().emptyState(onPick)}</>);

    expect(screen.getByText("Test Amigo")).toBeInTheDocument();
    expect(screen.getByText(/Answers as your unpublished draft/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Refunds\?/ }));
    fireEvent.click(screen.getByRole("button", { name: /^What it is for/ }));
    expect(onPick.mock.calls).toEqual([["Refunds?"], ["What can you help me with?"]]);
  });

  it("says a version answers, and has no face before the agent is read", () => {
    agentState.agent = undefined;
    render(<TestFrame agentId="a1" testing={{ draft: false, environmentId: "env-1" }} />);
    render(<>{lastProps().emptyState(vi.fn())}</>);

    expect(screen.getByText(/published version this environment serves/)).toBeInTheDocument();
    agentState.agent = {
      id: "a1",
      name: "Amigo",
      slug: "amigo",
      has_avatar: false,
      avatar_color: null,
    };
  });

  it("asks the panel to pin or unpin, and follows what the panel stored", () => {
    const parentPost = vi.spyOn(window.parent, "postMessage");
    render(<TestFrame agentId="a1" testing={{ draft: true, environmentId: null }} />);

    lastProps().pins.toggle("Hours?");
    expect(parentPost).toHaveBeenCalledWith({ type: PIN, text: "Hours?" }, window.location.origin);

    act(() => {
      writeTestPanel("a1", { ...readTestPanel("a1"), pinned: ["Hours?"] });
      window.dispatchEvent(new StorageEvent("storage"));
    });
    expect(lastProps().pins.pinned).toEqual(["Hours?"]);

    const onPick = vi.fn();
    render(<>{lastProps().emptyState(onPick)}</>);
    fireEvent.click(screen.getByRole("button", { name: "Unpin Hours?" }));
    expect(parentPost).toHaveBeenLastCalledWith(
      { type: PIN, text: "Hours?" },
      window.location.origin,
    );
    parentPost.mockRestore();
  });
});

describe("testingFromMode", () => {
  it.each([
    ["draft", { draft: true, environmentId: null }],
    ["env-1", { draft: false, environmentId: "env-1" }],
    ["default", { draft: false, environmentId: null }],
    [null, { draft: false, environmentId: null }],
  ])("reads %s", (mode, expected) => {
    expect(testingFromMode(mode)).toEqual(expected);
  });
});
