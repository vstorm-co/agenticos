import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatEmptyState } from "./chat-empty-state";
import type { Agent } from "@/types/agents";
import type { Mentionable } from "@/types/mention";

const env = vi.hoisted(() => ({
  agents: [] as Partial<Agent>[],
  items: [] as Mentionable[],
}));

vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: { full_name: "Ada Lovelace", email: "ada@example.com" } }),
  useAgents: () => ({ agents: env.agents }),
}));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: (agentId: string | null) => ({ items: agentId === "a1" ? env.items : [] }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { selectedAgentId: string }) => unknown) =>
    select({ selectedAgentId: "a1" }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const AGENT = { id: "a1", slug: "amigo", name: "Amigo", has_avatar: false, avatar_color: 0 };
const visuals: Mentionable = { kind: "capability", id: "visuals", name: "Visuals" };

describe("ChatEmptyState", () => {
  beforeEach(() => {
    env.agents = [{ ...AGENT, starters: [] }];
    env.items = [];
  });

  it("offers the agent's own first messages, which send as written (#2301)", async () => {
    // Even for an agent that draws: what its author wrote comes first.
    env.agents = [{ ...AGENT, starters: ["How do refunds work?", "Where is my order?"] }];
    env.items = [visuals];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "How do refunds work?" }));

    expect(onPick).toHaveBeenCalledWith("How do refunds work?");
    expect(screen.queryByText("Set up a routine")).toBeNull();
    expect(screen.queryByText("Plan a trip on a map")).toBeNull();
  });

  it("offers the chat's own for an agent with none, among them what it can do", async () => {
    env.items = [{ kind: "capability", id: "charts", name: "Charts" }];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /What can you do\?/ }));

    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("What can you do for me here?"));
    expect(screen.getByText("Set up a routine")).toBeInTheDocument();
    expect(screen.getByText("Summarize my docs")).toBeInTheDocument();
    expect(screen.queryByText("Plan a trip on a map")).toBeNull();
  });

  it("opens on one starter per kind of interactive answer for an agent that draws", async () => {
    env.items = [visuals];
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
