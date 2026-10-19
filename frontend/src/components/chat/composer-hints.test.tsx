import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Mentionable } from "@/types/mention";
import { ComposerHints, HINT_MS } from "./composer-hints";

vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const OFFERED: Mentionable[] = [
  { kind: "mcp", id: "n", name: "Notion", icon: "notion" },
  { kind: "capability", id: "ask_user", name: "Ask the user" },
  { kind: "capability", id: "web_research", name: "Web research" },
  { kind: "agent", id: "a", name: "Finance Analyst" },
  { kind: "skill", id: "s", name: "refund-policy" },
  { kind: "collection", id: "c", name: "Contracts" },
  { kind: "context", id: "x", name: "glossary" },
];

const shown = () => screen.getByTestId("composer-hints").querySelector(".composer-hint-in")!;

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("the empty composer's examples", () => {
  it("walks through what this agent has, one after another, then `/`", () => {
    render(<ComposerHints offered={OFFERED} commands={["clear", "summarize"]} />);
    const seen: string[] = [];
    for (let step = 0; step < 7; step += 1) {
      seen.push(shown().textContent!);
      act(() => vi.advanceTimersByTime(HINT_MS));
    }
    expect(seen).toEqual([
      "Type @ to point the agent at a server, a teammate or a skill",
      "Pull this week's updates from Notion and summarise them",
      // A capability that does work, not one that only asks.
      "Use Web research to work through the attached spreadsheet",
      "Ask Finance Analyst to double-check the numbers",
      "Follow refund-policy and draft a reply to this customer",
      "What does Contracts say about notice periods?",
      "Type /summarize to summarise this conversation, or / for every command",
    ]);
    // And round again, the last one sliding out as the first slides in.
    expect(shown()).toHaveTextContent(/^Type @/);
    expect(
      screen.getByTestId("composer-hints").querySelector(".composer-hint-out"),
    ).toHaveTextContent("/summarize");
  });

  it("says only what is there: no server, no capability that works, no commands", () => {
    render(
      <ComposerHints
        offered={[{ kind: "capability", id: "ask_user", name: "Ask the user" }]}
        commands={[]}
      />,
    );
    expect(shown()).toHaveTextContent(/^Type @/);
    act(() => vi.advanceTimersByTime(HINT_MS));
    expect(shown()).toHaveTextContent(/^Type @/);
  });

  it("names the first command when there is no summary to offer", () => {
    render(<ComposerHints offered={[]} commands={["clear"]} />);
    act(() => vi.advanceTimersByTime(HINT_MS));
    expect(shown()).toHaveTextContent("/clear");
  });
});
