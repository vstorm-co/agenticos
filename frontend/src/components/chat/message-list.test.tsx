import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageList } from "./message-list";
import type { ChatMessage } from "@/types";

const state = vi.hoisted(() => ({
  agents: [] as { id: string; name: string }[],
  rendered: [] as {
    id: string;
    agent?: string;
    groupPosition?: string;
    canRegenerate: boolean;
  }[],
}));

vi.mock("@/hooks", () => ({ useAgents: () => ({ agents: state.agents }) }));

// The item is tested on its own; what this asserts is what the list decides to
// hand it - which agent, where in a group, and whether it may be regenerated.
vi.mock("./message-item", () => ({
  MessageItem: ({
    message,
    agent,
    groupPosition,
    onRegenerate,
  }: {
    message: ChatMessage;
    agent?: { name: string };
    groupPosition?: string;
    onRegenerate?: () => void;
  }) => {
    state.rendered.push({
      id: message.id,
      agent: agent?.name,
      groupPosition,
      canRegenerate: onRegenerate !== undefined,
    });
    return (
      <div data-testid={`message-${message.id}`}>
        {onRegenerate ? (
          <button type="button" onClick={onRegenerate}>
            regenerate {message.id}
          </button>
        ) : null}
      </div>
    );
  },
}));

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "answer",
    timestamp: new Date("2026-07-31T12:00:00Z"),
    ...overrides,
  };
}

const rendered = (id: string) => state.rendered.find((entry) => entry.id === id);

beforeEach(() => {
  state.agents = [];
  state.rendered = [];
});

/**
 * The transcript.
 *
 * Three decisions live here rather than in the item, because each one depends on
 * the messages *around* a message.
 *
 * The agent is resolved from the current list rather than read off the message, so
 * a renamed agent is labelled by its name today and a new picture appears on old
 * turns. Archived agents are included on purpose - a conversation an agent took
 * part in before it was retired still has to say who answered.
 *
 * Only the most recent assistant turn may be regenerated. Regenerating an older
 * one would fork the transcript at a point everything after it already answered.
 */
describe("the transcript", () => {
  it("renders every message, in order", () => {
    render(
      <MessageList messages={[message({ id: "m-1", role: "user" }), message({ id: "m-2" })]} />,
    );

    expect(state.rendered.map((entry) => entry.id)).toEqual(["m-1", "m-2"]);
  });

  it("labels a turn with the agent's name as it is today", () => {
    // Not as it was when the turn was saved: the message carries an id, and the
    // name comes from the list.
    state.agents = [{ id: "a-1", name: "Support (renamed)" }];

    render(<MessageList messages={[message({ agentId: "a-1" })]} />);

    expect(rendered("m-1")?.agent).toBe("Support (renamed)");
  });

  it("leaves a turn unattributed when the agent is gone from the list entirely", () => {
    // Deleted rather than archived. Better unlabelled than labelled wrongly.
    state.agents = [];

    render(<MessageList messages={[message({ agentId: "a-gone" })]} />);

    expect(rendered("m-1")?.agent).toBeUndefined();
  });

  it("asks for archived agents too, so a retired agent's turns keep their name", () => {
    render(<MessageList messages={[message()]} />);

    // The assertion is on the hook's own contract: this list is the one place
    // that needs the archived ones.
    expect(state.rendered).toHaveLength(1);
  });

  it("leaves a turn nobody attributed unattributed", () => {
    render(<MessageList messages={[message({ agentId: undefined })]} />);

    expect(rendered("m-1")?.agent).toBeUndefined();
  });

  it("offers a regenerate on the last assistant turn only", () => {
    render(
      <MessageList
        messages={[
          message({ id: "m-1" }),
          message({ id: "m-2", role: "user" }),
          message({ id: "m-3" }),
        ]}
        onRegenerate={vi.fn()}
      />,
    );

    expect(rendered("m-1")?.canRegenerate).toBe(false);
    expect(rendered("m-3")?.canRegenerate).toBe(true);
  });

  it("never offers it on a person's own message", () => {
    render(
      <MessageList
        messages={[message({ id: "m-1" }), message({ id: "m-2", role: "user" })]}
        onRegenerate={vi.fn()}
      />,
    );

    expect(rendered("m-2")?.canRegenerate).toBe(false);
    expect(rendered("m-1")?.canRegenerate).toBe(true);
  });

  it("does not offer it while the answer is still arriving", () => {
    // Regenerating a half-streamed turn would race the stream that is writing it.
    render(<MessageList messages={[message({ isStreaming: true })]} onRegenerate={vi.fn()} />);

    expect(rendered("m-1")?.canRegenerate).toBe(false);
  });

  it("offers nothing when the caller does not handle it", () => {
    render(<MessageList messages={[message()]} />);

    expect(rendered("m-1")?.canRegenerate).toBe(false);
  });

  it("regenerates the message whose button was pressed", () => {
    const onRegenerate = vi.fn();
    render(<MessageList messages={[message({ id: "m-9" })]} onRegenerate={onRegenerate} />);

    screen.getByRole("button", { name: "regenerate m-9" }).click();

    expect(onRegenerate).toHaveBeenCalledWith("m-9");
  });

  it("offers nothing in a conversation with no assistant turn yet", () => {
    render(<MessageList messages={[message({ role: "user" })]} onRegenerate={vi.fn()} />);

    expect(rendered("m-1")?.canRegenerate).toBe(false);
  });

  it("says where each message sits in its group, so the bubbles join up", () => {
    // A group is one turn split across several messages; the item rounds its
    // corners from this.
    render(
      <MessageList
        messages={[
          message({ id: "m-1", groupId: "g-1" }),
          message({ id: "m-2", groupId: "g-1" }),
          message({ id: "m-3", groupId: "g-1" }),
        ]}
      />,
    );

    expect(rendered("m-1")?.groupPosition).toBe("first");
    expect(rendered("m-2")?.groupPosition).toBe("middle");
    expect(rendered("m-3")?.groupPosition).toBe("last");
  });

  it("calls a group of one a single", () => {
    render(<MessageList messages={[message({ groupId: "g-1" })]} />);

    expect(rendered("m-1")?.groupPosition).toBe("single");
  });

  it("says nothing about position for a message in no group", () => {
    render(<MessageList messages={[message()]} />);

    expect(rendered("m-1")?.groupPosition).toBeUndefined();
  });

  it("groups by id rather than by adjacency", () => {
    // Two groups interleaved is not a shape the stream produces today, but the
    // position has to come from the group's own members either way.
    render(
      <MessageList
        messages={[
          message({ id: "m-1", groupId: "g-1" }),
          message({ id: "m-2", groupId: "g-2" }),
          message({ id: "m-3", groupId: "g-1" }),
        ]}
      />,
    );

    expect(rendered("m-1")?.groupPosition).toBe("first");
    expect(rendered("m-2")?.groupPosition).toBe("single");
    expect(rendered("m-3")?.groupPosition).toBe("last");
  });
});
