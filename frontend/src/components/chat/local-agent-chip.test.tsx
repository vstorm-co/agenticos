import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { LocalTarget } from "@/lib/desktop/commands";
import type { Agent } from "@/types/agents";
import { LocalAgentChip } from "./local-agent-chip";

const env = vi.hoisted(() => ({
  shell: { platform: "macos", version: "0.2.0", window: "main", vibrancy: true } as unknown,
  agents: [] as unknown[],
  target: null as unknown,
}));

vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: env.agents }) }));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { selectedAgentId: string }) => unknown) =>
    select({ selectedAgentId: "a1" }),
  useConversationStore: (select: (state: { currentConversationId: string }) => unknown) =>
    select({ currentConversationId: "c1" }),
}));
vi.mock("@/stores/work-on-store", () => ({
  useWorkOnStore: (select: (state: { targetFor: () => unknown }) => unknown) =>
    select({ targetFor: () => env.target }),
}));

function agent(local: Agent["local_coding_agent"]): unknown {
  return { id: "a1", local_coding_agent: local };
}
const folder = (over: Partial<LocalTarget> = {}): LocalTarget => ({
  folder: "/Users/me/work/agenticos",
  mode: "full_access",
  ...over,
});

beforeEach(() => {
  env.shell = { platform: "macos", version: "0.2.0", window: "main", vibrancy: true };
  env.agents = [agent({ harness: "claude_code", access: "edit" })];
  env.target = folder();
});

it("names the agent, the folder and what it may do", () => {
  render(<LocalAgentChip />);
  expect(screen.getByText("Claude Code · agenticos · can edit")).toBeInTheDocument();
  expect(screen.queryByRole("status")).toBeNull();
});

it("says read only for an agent that cannot change anything", () => {
  env.agents = [agent({ harness: "codex", access: "read_only" })];
  render(<LocalAgentChip />);
  expect(screen.getByText("Codex · agenticos · read only")).toBeInTheDocument();
});

it("asks for a folder when the chat has none, or only whole-computer access", () => {
  env.target = null;
  const { rerender } = render(<LocalAgentChip />);
  expect(screen.getByRole("status")).toHaveTextContent(/choose a folder under Chat controls/);
  env.target = folder({ computer_grant: "grant-1" });
  rerender(<LocalAgentChip />);
  expect(screen.getByRole("status")).toHaveTextContent(/choose a folder/);
});

it("says the folder needs full access, because the agent runs as the person", () => {
  env.target = folder({ mode: "workspace_write" });
  render(<LocalAgentChip />);
  expect(screen.getByRole("status")).toHaveTextContent(/needs full access/);
});

it("shows nothing for an agent that runs no coding agent here, or outside the desktop app", () => {
  env.agents = [agent(null)];
  const { container, rerender } = render(<LocalAgentChip />);
  expect(container).toBeEmptyDOMElement();
  env.agents = [agent({ harness: "claude_code", access: "edit" })];
  env.shell = null;
  rerender(<LocalAgentChip />);
  expect(container).toBeEmptyDOMElement();
});
