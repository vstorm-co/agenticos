import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { ChatPrompt } from "@/components/chat/chat-container";
import { ChatScope, useChatStore } from "@/stores";

import { TestChat, testingFromMode } from "./test-chat";

const { container } = vi.hoisted(() => ({ container: vi.fn() }));

vi.mock("@/components/chat/chat-container", () => ({
  ChatContainer: (props: unknown) => {
    container(props);
    return null;
  },
}));
const agentState: { agent: unknown } = {
  agent: { id: "a1", name: "Amigo", slug: "amigo", has_avatar: false, avatar_color: null },
};
vi.mock("@/hooks/use-agents", () => ({ useAgent: () => agentState }));

const lastProps = () =>
  container.mock.calls.at(-1)![0] as {
    prompt: ChatPrompt | null;
    testing: unknown;
    pins: { pinned: readonly string[]; toggle: (text: string) => void };
    emptyState: (onPick: (prompt: string) => void) => React.ReactNode;
  };

interface Props {
  ask?: ChatPrompt | null;
  replay?: number;
  pinned?: readonly string[];
  onTogglePin?: (text: string) => void;
  testing?: { draft: boolean; environmentId: string | null };
}

/** The chat in a scope of its own, as the panel renders it. */
function chat({
  ask = null,
  replay = 0,
  pinned = [],
  onTogglePin = vi.fn(),
  testing = { draft: true, environmentId: null },
}: Props = {}) {
  return (
    <ChatScope agentId="a1">
      <TestChat
        agentId="a1"
        testing={testing}
        pinned={pinned}
        onTogglePin={onTogglePin}
        ask={ask}
        replay={replay}
      />
    </ChatScope>
  );
}

/** Whatever the scoped chat store holds, for the replay to read. */
function Transcript({ texts }: { texts: string[] }) {
  const api = useChatStore.useApi();
  if (api.getState().messages.length === 0)
    api.setState({
      messages: texts.map((content, index) => ({
        id: String(index),
        role: index % 2 === 0 ? "user" : "assistant",
        content,
        timestamp: new Date(),
      })),
    });
  return null;
}

describe("the test panel's conversation", () => {
  it("chats with the agent being built, as a test", () => {
    const testing = { draft: true, environmentId: null };
    render(chat({ testing }));

    expect(lastProps().testing).toEqual(testing);
    expect(lastProps().prompt).toBeNull();
  });

  it("sends what the panel asks", () => {
    const { rerender } = render(chat());

    rerender(chat({ ask: { id: 1, text: "Refunds?" } }));
    expect(lastProps().prompt?.text).toBe("Refunds?");
  });

  it("passes on that the draft is still saving", () => {
    render(
      <ChatScope agentId="a1">
        <TestChat
          agentId="a1"
          testing={{ draft: true, environmentId: null }}
          pinned={[]}
          onTogglePin={vi.fn()}
          ask={null}
          replay={0}
          holdSending
        />
      </ChatScope>,
    );

    expect((container.mock.calls.at(-1)![0] as { holdSending: boolean }).holdSending).toBe(true);
  });

  it("replays the last question of its own conversation", () => {
    const at = (replay: number) => (
      <ChatScope agentId="a1">
        <Transcript texts={["first", "answer", "last"]} />
        <TestChat
          agentId="a1"
          testing={{ draft: true, environmentId: null }}
          pinned={[]}
          onTogglePin={vi.fn()}
          ask={null}
          replay={replay}
        />
      </ChatScope>
    );
    const { rerender } = render(at(0));

    rerender(at(1));

    expect(lastProps().prompt?.text).toBe("last");
  });

  it("does not send the last conversation's question again when it starts afresh", () => {
    // A new conversation is a new scope, mounted while the panel still holds
    // the question and the replay count it had.
    render(chat({ ask: { id: 3, text: "Refunds?" }, replay: 2 }));

    expect(lastProps().prompt).toBeNull();
  });

  it("replays nothing before anything was asked", () => {
    const { rerender } = render(chat());

    rerender(chat({ replay: 1 }));

    expect(lastProps().prompt).toBeNull();
  });
});

describe("the conversation's opening, as /chat's (#2075)", () => {
  it("names the agent and what answers, then its pinned questions and the starters", () => {
    render(chat({ pinned: ["Refunds?"] }));
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
    render(chat({ testing: { draft: false, environmentId: "env-1" } }));
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

  it("pins and unpins through the panel, from the conversation and its opening", () => {
    const onTogglePin = vi.fn();
    render(chat({ pinned: ["Hours?"], onTogglePin }));

    lastProps().pins.toggle("Refunds?");
    expect(lastProps().pins.pinned).toEqual(["Hours?"]);
    render(<>{lastProps().emptyState(vi.fn())}</>);
    fireEvent.click(screen.getByRole("button", { name: "Unpin Hours?" }));

    expect(onTogglePin.mock.calls).toEqual([["Refunds?"], ["Hours?"]]);
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
