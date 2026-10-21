import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NO_TEAMS_POST, TeamsPostField } from "./teams-post-field";
import type { TeamsConversation } from "@/types/channels";

const conversations = vi.hoisted(() => ({ value: [] as TeamsConversation[] }));
vi.mock("@/hooks/use-channel-bots", () => ({
  useTeamsConversations: () => ({ data: conversations.value }),
}));

function conversation(overrides: Partial<TeamsConversation>): TeamsConversation {
  return {
    id: "c1",
    bot_id: "b1",
    name: "General",
    conversation_type: "channel",
    last_activity_at: "2026-10-16T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  conversations.value = [];
});

describe("TeamsPostField (#1985)", () => {
  it("is not drawn where there is nowhere to post", () => {
    const { container } = render(<TeamsPostField value={NO_TEAMS_POST} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the chosen channel", () => {
    conversations.value = [conversation({ id: "c1", name: "Releases" })];
    render(<TeamsPostField value="c1" onChange={vi.fn()} />);
    expect(screen.getByText("Releases")).toBeInTheDocument();
  });

  it.each([
    ["channel", "A Teams channel"],
    ["groupChat", "A Teams group chat"],
  ] as const)("names an unnamed %s by what it is", (kind, label) => {
    conversations.value = [conversation({ id: "c2", name: null, conversation_type: kind })];
    render(<TeamsPostField value="c2" onChange={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
