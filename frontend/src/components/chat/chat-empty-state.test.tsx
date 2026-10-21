import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentSelectionStore } from "@/stores";
import type { Agent } from "@/types/agents";

import { ChatEmptyState } from "./chat-empty-state";

const env = vi.hoisted(() => ({ agents: [] as Partial<Agent>[] }));
vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: { full_name: "Ada Lovelace", email: "ada@example.com" } }),
  useAgents: () => ({ agents: env.agents }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => null }));

const AGENT = { id: "a-1", slug: "helper", name: "Helper", has_avatar: false };

beforeEach(() => useAgentSelectionStore.setState({ selectedAgentId: "a-1" }));

describe("ChatEmptyState", () => {
  it("offers the agent's own first messages, which send as written", async () => {
    env.agents = [{ ...AGENT, starters: ["How do refunds work?", "Where is my order?"] }];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "How do refunds work?" }));

    expect(onPick).toHaveBeenCalledWith("How do refunds work?");
    expect(screen.queryByText("Set up a routine")).toBeNull();
  });

  it("offers the chat's own for an agent with none, among them what it can do", async () => {
    env.agents = [{ ...AGENT, starters: [] }];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /What can you do\?/ }));

    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("What can you do for me here?"));
    expect(screen.getByText("Set up a routine")).toBeInTheDocument();
  });
});
