import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STUCK_AFTER_MS, useAssistantSignals } from "./use-assistant-signals";

const state = vi.hoisted(() => ({
  can: (_: string): boolean => true,
  agents: [{ id: "a" }] as { id: string }[],
  agentsLoading: false,
  approvals: 0,
  failed: [] as { id: string }[],
  userId: "u-1" as string | null,
  runsOptions: null as unknown,
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: state.can }),
  useAgents: () => ({ agents: state.agents, isLoading: state.agentsLoading }),
  useApprovals: () => ({ total: state.approvals }),
  useRuns: (_agent: unknown, options: unknown) => {
    state.runsOptions = options;
    return { runs: state.failed };
  },
}));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (s: { user: { id: string } | null }) => unknown) =>
    pick({ user: state.userId === null ? null : { id: state.userId } }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  state.can = () => true;
  state.agents = [{ id: "a" }];
  state.agentsLoading = false;
  state.approvals = 0;
  state.failed = [];
  state.userId = "u-1";
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("useAssistantSignals", () => {
  it("reports what is waiting and an organization with nothing in it yet", () => {
    state.approvals = 3;
    state.agents = [];
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current).toMatchObject({ pendingApprovals: 3, noAgents: true });
  });

  it("does not call a still-loading organization empty", () => {
    state.agents = [];
    state.agentsLoading = true;
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current.noAgents).toBe(false);
  });

  it("names the reader's own latest failed run of the last day", () => {
    state.failed = [{ id: "run-2" }, { id: "run-1" }];
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current.failedRunId).toBe("run-2");
    expect(state.runsOptions).toMatchObject({ enabled: true, statuses: ["failed"], userId: "u-1" });
  });

  it("asks for no runs without runs:view or a signed-in reader", () => {
    state.can = () => false;
    renderHook(() => useAssistantSignals());
    expect(state.runsOptions).toMatchObject({ enabled: false });

    state.can = () => true;
    state.userId = null;
    renderHook(() => useAssistantSignals());
    expect(state.runsOptions).toMatchObject({ enabled: false, userId: undefined });
  });

  it("notices a form left open for a minute, by its title", () => {
    document.body.innerHTML = `
      <div role="dialog" aria-labelledby="t"><h2 id="t"> Create a knowledge base </h2></div>`;
    const { result } = renderHook(() => useAssistantSignals());

    wait(30_000);
    expect(result.current.stuckIn).toBeNull();
    wait(STUCK_AFTER_MS);
    expect(result.current.stuckIn).toBe("Create a knowledge base");

    document.body.innerHTML = "";
    wait(5000);
    expect(result.current.stuckIn).toBeNull();
  });

  it("starts the minute again for a different form", () => {
    document.body.innerHTML = `<div role="dialog" aria-label="Invite people"></div>`;
    const { result } = renderHook(() => useAssistantSignals());
    wait(STUCK_AFTER_MS + 5000);
    expect(result.current.stuckIn).toBe("Invite people");

    document.title = "Agents";
    document.body.innerHTML = `<div role="dialog"></div>`;
    wait(5000);
    expect(result.current.stuckIn).toBeNull();
    wait(STUCK_AFTER_MS);
    expect(result.current.stuckIn).toBe("Agents");
  });

  it("never counts its own window as a form", () => {
    document.body.innerHTML = `<div role="dialog" data-assistant-window aria-label="AI Architect"></div>`;
    const { result } = renderHook(() => useAssistantSignals());

    wait(STUCK_AFTER_MS + 5000);

    expect(result.current.stuckIn).toBeNull();
  });
});
