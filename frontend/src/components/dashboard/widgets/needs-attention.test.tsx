import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { Perm, type Permission } from "@/types/permissions";
import type { AgentAttention } from "@/types/stats";
import { NeedsAttentionWidget } from "./needs-attention";

const state = vi.hoisted(() => ({
  agents: [] as AgentAttention[],
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  editable: [] as { id: string; can_edit: boolean }[],
  granted: new Set<string>(),
  asked: [] as unknown[],
}));
vi.mock("@/hooks", () => ({
  useAgentAttention: (...args: unknown[]) => {
    state.asked.push(args);
    return state;
  },
  useAgents: ({ enabled }: { enabled: boolean }) => ({ agents: enabled ? state.editable : [] }),
  usePermissions: () => ({ can: (perm: Permission) => state.granted.has(perm) }),
}));
const pointAt = vi.hoisted(() => vi.fn().mockResolvedValue(true));
vi.mock("@/lib/assistant-highlight", () => ({ pointAt }));

const PERIOD: Period = { preset: "30d", from: "2026-09-23", to: "2026-10-22" };

function widget() {
  return render(
    <TooltipProvider>
      <NeedsAttentionWidget title="Needs attention" hint="" period={PERIOD} />
    </TooltipProvider>,
  );
}

function item(overrides: Partial<AgentAttention>): AgentAttention {
  return {
    agent_id: "a1",
    name: "Refund desk",
    rated_down: 0,
    failed_runs: 0,
    failing_suites: 0,
    ...overrides,
  };
}

beforeEach(() => {
  state.agents = [];
  state.isLoading = false;
  state.error = null;
  state.refetch = vi.fn();
  state.editable = [];
  state.granted = new Set([Perm.agentsEdit]);
  state.asked = [];
  pointAt.mockClear();
});

describe("NeedsAttentionWidget", () => {
  it("lists each agent with what it counts, and Improve on those the reader may edit", async () => {
    state.agents = [
      item({ rated_down: 5, failing_suites: 1 }),
      item({ agent_id: "a2", name: "Clerk", failed_runs: 2 }),
    ];
    state.editable = [
      { id: "a1", can_edit: true },
      { id: "a2", can_edit: false },
    ];
    widget();

    expect(state.asked[0]).toEqual([{ from: PERIOD.from, to: PERIOD.to }]);
    expect(screen.getByRole("link", { name: "Refund desk" })).toHaveAttribute("href", "/agents/a1");
    expect(screen.getByText("5 answers rated down · 1 failing suite")).toBeInTheDocument();
    expect(screen.getByText("2 failed runs")).toBeInTheDocument();
    const improve = screen.getAllByRole("link", { name: "Improve" });
    expect(improve).toHaveLength(1);
    expect(improve[0]).toHaveAttribute("href", "/agents/a1?tab=build");
    await userEvent.click(improve[0]!);
    expect(pointAt).toHaveBeenCalledWith("agent-assistant-strip");
  });

  it("offers no Improve to a reader who may edit no agent", () => {
    state.granted = new Set();
    state.agents = [item({ rated_down: 1 })];
    widget();

    expect(screen.getByText("1 answer rated down")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Improve" })).toBeNull();
  });

  it("says nothing needs attention, waits, and offers a retry", async () => {
    const { unmount } = widget();
    expect(screen.getByText("Nothing needs attention")).toBeInTheDocument();
    unmount();

    state.isLoading = true;
    const loading = widget();
    expect(screen.queryByText("Nothing needs attention")).toBeNull();
    loading.unmount();

    state.isLoading = false;
    state.error = new Error("boom");
    widget();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalled();
  });
});
