import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ImproveButton, ImproveLink } from "./improve-link";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  sessions: [] as { id: string; status: string; created_at: string }[],
  attention: [] as { agent_id: string; rated_down: number; failed_runs: number }[],
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push }) }));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovements: () => ({ sessions: state.sessions }),
}));
vi.mock("@/hooks/use-usage-stats", () => ({
  useAgentAttention: () => ({ agents: state.attention }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.sessions = [];
  state.attention = [];
});

it("starts a new session when none is open, after storing the page's draft", async () => {
  const persist = vi.fn().mockResolvedValue(true);
  render(<ImproveButton agentId="a1" persist={persist} />);
  const button = screen.getByRole("button", { name: "Improve" });
  expect(button).not.toHaveClass("bg-primary");
  expect(screen.queryByTestId("improve-attention")).not.toBeInTheDocument();
  const icon = button.querySelector("svg.lucide-trending-up")!;
  expect(icon).toBeInTheDocument();
  expect(icon.closest('[aria-hidden="true"]')).not.toBeNull();
  await userEvent.click(button);
  expect(persist).toHaveBeenCalled();
  expect(state.push).toHaveBeenCalledWith("/agents/a1/improve/new");
});

it("reopens the session still open, marking an agent that needs it without leading", async () => {
  state.sessions = [
    { id: "done", status: "published", created_at: "2026-10-25T10:00:00Z" },
    { id: "open", status: "ready", created_at: "2026-10-24T10:00:00Z" },
  ];
  state.attention = [{ agent_id: "a1", rated_down: 0, failed_runs: 1 }];
  render(<ImproveButton agentId="a1" size="sm" tour="strip-improve" />);
  const button = screen.getByRole("button", {
    name: "Needs attention: 1 failed run. Improve this agent",
  });
  expect(button).not.toHaveClass("bg-primary");
  expect(button).toHaveClass("border");
  expect(screen.getByTestId("improve-attention")).toBeInTheDocument();
  expect(button.querySelector("svg.lucide-trending-up")).toBeInTheDocument();
  expect(button).toHaveAttribute("data-tour", "strip-improve");
  await userEvent.click(button);
  expect(state.push).toHaveBeenCalledWith("/agents/a1/improve/open");
});

it("goes nowhere while the page's draft cannot be stored", async () => {
  render(<ImproveButton agentId="a1" persist={vi.fn().mockResolvedValue(false)} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve" }));
  expect(state.push).not.toHaveBeenCalled();
});

it("links to the start screen, which forwards to a session still open", () => {
  render(<ImproveLink agentId="a1">Improve</ImproveLink>);
  expect(screen.getByRole("link", { name: "Improve" })).toHaveAttribute(
    "href",
    "/agents/a1/improve/new?resume=1",
  );
});

it.each(["accepted", "published", "rejected", "stopped", "failed", "cancelled", "stale"])(
  "starts the next session past one that is %s",
  async (status) => {
    state.sessions = [{ id: "over", status, created_at: "2026-10-25T10:00:00Z" }];
    render(<ImproveButton agentId="a1" />);
    await userEvent.click(screen.getByRole("button", { name: "Improve" }));
    expect(state.push).toHaveBeenCalledWith("/agents/a1/improve/new");
  },
);
