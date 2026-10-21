import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "@/stores";
import type { Agent } from "@/types/agents";

import { VoiceCaptions } from "./voice-captions";

const NONE: ReadonlySet<string> = new Set();

beforeEach(() => {
  useAuthStore.setState({ user: { id: "u-1", email: "k@example.test" } as never });
});

describe("VoiceCaptions", () => {
  it("draws the faces a page passes in place of the signed-in person's and the agent's", () => {
    // The hosted page has no signed-in person, and draws its own saved turns:
    // a caption must wear the faces its saved turn will.
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={NONE}
        callerAvatar={<span data-testid="caller-face" />}
        agentAvatar={<span data-testid="agent-face" />}
        captions={[
          { turnId: "t1", part: 0, role: "user", text: "Weather?", final: true },
          { turnId: "t2", part: 0, role: "assistant", text: "Sunny", final: true },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(within(visible).getByTestId("caller-face")).toBeInTheDocument();
    expect(within(visible).getByTestId("agent-face")).toBeInTheDocument();
    expect(visible.querySelector(".lucide-bot")).toBeNull();
  });

  it("hands each turn to the page that draws it as its saved message", () => {
    // `/chat` draws a spoken turn as the message it becomes, so nothing jumps
    // when the saved one takes its place.
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={new Set(["t0"])}
        captions={[
          { turnId: "t0", part: 0, role: "user", text: "Saved already", final: true },
          { turnId: "t1", part: 0, role: "assistant", text: "Sunny", final: false },
          { turnId: "t1", part: 1, role: "assistant", text: "today", final: false },
        ]}
        renderTurn={(turn) => (
          <p data-testid="page-turn">{`${turn.role}:${turn.text}:${String(turn.live)}`}</p>
        )}
      />,
    );
    expect(screen.getAllByTestId("page-turn").map((node) => node.textContent)).toEqual([
      "assistant:Sunny today:true",
    ]);
  });

  it("shows the words to sighted readers and announces whole sentences to screen readers", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={NONE}
        captions={[
          { turnId: "t1", part: 0, role: "user", text: "Weather in Warsaw?", final: true },
          { turnId: "t2", part: 0, role: "assistant", text: "It is eigh", final: false },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(visible).toHaveAttribute("aria-hidden", "true");
    expect(visible).toHaveTextContent("It is eigh");
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("You: Weather in Warsaw?");
    expect(live).not.toHaveTextContent("It is eigh");
  });

  it("marks the message being spoken as live, and both as said by voice", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={NONE}
        captions={[
          { turnId: "t1", part: 0, role: "user", text: "Weather?", final: true },
          { turnId: "t2", part: 0, role: "assistant", text: "It is", final: false },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(within(visible).getAllByText("Live")).toHaveLength(1);
    expect(within(visible).getAllByText("Voice")).toHaveLength(2);
    expect(within(visible).getByText("Support")).toBeInTheDocument();
  });

  it("names the agent when its line is finished", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={NONE}
        captions={[
          { turnId: "t2", part: 0, role: "assistant", text: "It is eight degrees.", final: true },
        ]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Support: It is eight degrees.");
  });

  it("announces nothing before a line is finished", () => {
    render(<VoiceCaptions agentName="Support" hidden={NONE} captions={[]} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("puts every part of one answer in one message, live until the last part is final", () => {
    const agent = { id: "a-1", slug: "support", has_avatar: false } as Agent;
    render(
      <VoiceCaptions
        agentName="Support"
        agent={agent}
        hidden={NONE}
        captions={[
          { turnId: "a1", part: 0, role: "assistant", text: "Let me check.", final: true },
          { turnId: "a1", part: 1, role: "assistant", text: "Eight degrees.", final: false },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(visible).toHaveTextContent("Let me check. Eight degrees.");
    expect(within(visible).getAllByText("Live")).toHaveLength(1);
    expect(visible.querySelector(".voice-live-rule")).not.toBeNull();
  });

  it("marks nothing live once the call is over", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={NONE}
        speaking={false}
        captions={[
          { turnId: "a1", part: 0, role: "assistant", text: "Let me", final: false },
          { turnId: "a1", part: 1, role: "assistant", text: "check", final: false },
        ]}
      />,
    );
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("leaves out a turn the conversation already holds as a message", () => {
    useAuthStore.setState({ user: null });
    render(
      <VoiceCaptions
        agentName="Support"
        hidden={new Set(["t1"])}
        captions={[
          { turnId: "t1", part: 0, role: "user", text: "Saved already.", final: true },
          { turnId: "t2", part: 0, role: "user", text: "Still speaking", final: false },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(visible).not.toHaveTextContent("Saved already.");
    expect(visible).toHaveTextContent("Still speaking");
  });
});
