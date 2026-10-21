import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatEmptyState } from "./chat-empty-state";
import type { Mentionable } from "@/types/mention";

const { offered } = vi.hoisted(() => ({ offered: { items: [] as Mentionable[] } }));

vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: { full_name: "Ada Lovelace", email: "ada@example.com" } }),
  useAgents: () => ({
    agents: [{ id: "a1", slug: "amigo", name: "Amigo", has_avatar: false, avatar_color: 0 }],
  }),
}));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: (agentId: string | null) => ({ items: agentId === "a1" ? offered.items : [] }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { selectedAgentId: string }) => unknown) =>
    select({ selectedAgentId: "a1" }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const visuals: Mentionable = { kind: "capability", id: "visuals", name: "Visuals" };

describe("ChatEmptyState", () => {
  beforeEach(() => {
    offered.items = [];
  });

  it("opens on the general starters for an agent that does not draw", () => {
    offered.items = [{ kind: "capability", id: "charts", name: "Charts" }];
    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.getByText("Summarize my docs")).toBeInTheDocument();
    expect(screen.queryByText("Plan a trip on a map")).toBeNull();
  });

  it("opens on one starter per kind of interactive answer for an agent that draws", async () => {
    offered.items = [visuals];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    for (const title of [
      "Explain it in 3D",
      "Compare, then chart it",
      "Make a calculator",
      "Plan a trip on a map",
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.queryByText("Summarize my docs")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /^Plan a trip on a map/ }));
    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("on a map"));
  });
});
