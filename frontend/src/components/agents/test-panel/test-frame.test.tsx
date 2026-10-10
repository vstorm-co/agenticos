import { describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";

import { TestFrame, testingFromMode } from "./test-frame";
import { ASK, NEW, REPLAY } from "@/lib/assistant-messages";
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
  container.mock.calls.at(-1)![0] as { prompt: { text: string } | null; testing: unknown };

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
